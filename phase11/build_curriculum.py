"""Build the reviewed Phase11 curriculum and verify every new executable example."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'phase10/dist/curriculum.json'
BASE_SHA = 'a418cbb4f6f64fc809716f4fc634ba6b6df50e75e083bdd6925cfbde4d80df62'
BUNDLE = ROOT / 'dist/curriculum.json'
ARCHIVES = ROOT.parent / 'phase2/apps/web/public/projects'
MODULES = (('algorithms','alg',8,4), ('oop','oop',6,2), ('problem-solving','solve',6,4))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compose():
    previous = BASE.read_bytes()
    require(hashlib.sha256(previous).hexdigest() == BASE_SHA, 'Reviewed Phase10 changed')
    bundle = json.loads(previous)
    sample, graph = bundle['sample'], bundle['graph']
    sample.update(releaseId='phase11-ar-v1', title='منهج البرمجة والبيانات وحل المشكلات',
                  intro='ابدأ بالأساسيات واختر لغتك أو تخصصك. عمّق حل المشكلات والخوارزميات وتصميم الكائنات بخطة تعيد استخدام ما تعلمته.')
    graph['releaseId'] = 'phase11-ar-v1'
    terms = {term['term'] for term in sample['glossary']}
    modules = []
    for name, prefix, count, labs in MODULES:
        module = json.loads((ROOT / 'content' / (name+'.json')).read_bytes())
        modules.append(module)
        expected = [f'{prefix}-{i:02}' for i in range(1,count+1)]
        require([row['id'] for row in module['lessons']] == expected, name+': lesson order')
        require([row['id'] for row in module['graphLessons']] == expected, name+': graph lesson order')
        require(module['track']['lessonIds'] == expected, name+': track order')
        require(module['goal']['id'] == module['track']['id'] == name, name+': goal/track')
        require(module['goal']['skillIds'] == [skill['id'] for skill in module['skills']], name+': goal skills')
        require(all(len(lesson['exercises']) == 3 for lesson in module['lessons']), name+': expected three graded exercises')
        require(len(module['labs']) == labs, name+': lab count')
        require(module['project']['lessonId'] == expected[-1], name+': capstone lesson')
        require(module['project']['download'] == f'/projects/{name}-starter-v1.zip', name+': download')
        sample['lessons'].extend(module['lessons'])
        sample['tracks'].append(module['track'])
        sample['projects'].append(module['project'])
        graph['skills'].extend(module['skills'])
        graph['lessons'].extend(module['graphLessons'])
        graph['goals'].append(module['goal'])
        bundle['codeLab'].extend({key:value for key,value in lab.items() if key != 'solution'} for lab in module['labs'])
        for term in module['glossary']:
            if term['term'] not in terms:
                sample['glossary'].append(term)
                terms.add(term['term'])
    exercises = [exercise for lesson in sample['lessons'] for exercise in lesson['exercises']]
    for rows in (sample['lessons'],sample['tracks'],sample['projects'],graph['skills'],graph['lessons'],graph['goals'],bundle['codeLab'],exercises):
        require(len({row['id'] for row in rows}) == len(rows), 'Duplicate IDs')
    require((len(sample['lessons']),len(exercises),len(graph['goals']),len(bundle['codeLab'])) == (110,304,18,46), 'Unexpected reviewed counts')
    payload = (json.dumps(bundle,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
    require(len(payload) <= 1048576, 'Bundle exceeds API import limit')
    return payload, modules


def execute(language, source, stdin):
    binary = sys.executable if language == 'python' else shutil.which('node')
    require(binary is not None, 'Missing runtime '+language)
    with tempfile.TemporaryDirectory(prefix='nexora-phase11-example-') as temp:
        path = Path(temp) / ('example.py' if language == 'python' else 'example.cjs')
        path.write_text(source,encoding='utf-8')
        command = [binary,'-I','-B',str(path)] if language == 'python' else [binary,str(path)]
        env = dict(os.environ,PYTHONIOENCODING='utf-8')
        result = subprocess.run(command,input=stdin.encode('utf-8'),capture_output=True,timeout=15,env=env)
        require(result.returncode == 0 and not result.stderr, f'{language} execution failed: '+result.stderr.decode('utf-8','replace'))
        return result.stdout.decode('utf-8').replace('\r\n','\n')


def verify_examples(modules):
    example_count = lab_count = 0
    for module in modules:
        examples = {(lesson['id'],i):example for lesson in module['lessons'] for i,example in enumerate(lesson['examples'])
                    if example['language'] in ('python','javascript')}
        checked = set()
        for case in module['exampleChecks']:
            key = case['lessonId'],case['index']
            require(key in examples, 'Example check points outside executable sources')
            example = examples[key]
            require(execute(example['language'],example['code'],case['input']) == case['output'].replace('\r\n','\n'), f'{key}: displayed output mismatch')
            checked.add(key)
            example_count += 1
        require(checked == examples.keys(), 'An executable example has no check')
        for lab in module['labs']:
            require(1 <= len(lab['hiddenTests']) <= 3 and 'solution' in lab, 'Invalid authored lab')
            for case in [{'input':lab['sampleInput'],'expectedOutput':lab['sampleOutput']},*lab['hiddenTests']]:
                require(execute(lab['language'],lab['solution'],case['input']) == case['expectedOutput'].replace('\r\n','\n'), lab['id']+': lab solution differs')
                lab_count += 1
    print(f'PASSED: {example_count} executable Python/JavaScript examples and {lab_count} lab solution cases')


def project_files(name):
    folder = ROOT / 'project' / name / 'starter'
    require(folder.is_dir(), name+': missing starter')
    excluded = {'.local','__pycache__','node_modules','dist','.git','.venv','venv','coverage'}
    files = {}
    for path in sorted(folder.rglob('*')):
        relative = path.relative_to(folder)
        if any(part in excluded for part in relative.parts) or not path.is_file():
            continue
        require(not path.is_symlink(), 'Starter contains a symbolic link')
        if path.suffix not in {'.py','.cjs','.mjs','.js','.json','.md','.txt'} and path.name != '.gitignore':
            continue
        files[relative.as_posix()] = path.read_bytes()
    require('README.md' in files and 'LICENSES.md' in files, name+': missing learner/license instructions')
    require(any(path.endswith('.py') for path in files), name+': missing Python source')
    if name != 'oop':
        require(any(path.endswith(('.js','.mjs','.cjs')) for path in files), name+': missing JavaScript source')
    return files


def package(check):
    ARCHIVES.mkdir(parents=True,exist_ok=True)
    for name,*_ in MODULES:
        files = project_files(name)
        archive = ARCHIVES / (name+'-starter-v1.zip')
        if check:
            with zipfile.ZipFile(archive) as zipped:
                require(zipped.namelist() == list(files), name+': archive member mismatch')
                require(all(zipped.read(path) == data for path,data in files.items()), name+': archive source mismatch')
        else:
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zipped:
                for path,data in files.items():
                    entry = zipfile.ZipInfo(path,date_time=(2026,11,19,0,0,0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.external_attr = 0o100644 << 16
                    zipped.writestr(entry,data)
        print(f'PASSED: {archive.name} matches {len(files)} authored files')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    payload,modules = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, 'Bundle differs from authored source')
        verify_examples(modules)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    package(args.check)
    print('phase11-ar-v1: 110 lessons,304 graded exercises,18 goals,46 labs')
    print('SHA-256: '+hashlib.sha256(payload).hexdigest())


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired,zipfile.BadZipFile) as error:
        sys.exit('Phase11 check failed: '+str(error))
