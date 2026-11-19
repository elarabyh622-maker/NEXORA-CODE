"""Build Phase 10 and check its JavaScript, React rendering, TypeScript and download sources."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase9/dist/curriculum.json"
BASE_SHA256 = "bf66b58d76aaa54bd0d760eecde443cb7c98081b474c0e04ffe92ee9973d525a"
RELEASE = "phase10-ar-v1"
MODULES = (("javascript-projects", "jsproj", 4), ("react", "react", 7), ("typescript-react", "tsreact", 3))
BUNDLE = ROOT / "dist/curriculum.json"
JS_PROJECT = ROOT / "project/reference-js"
TS_PROJECT = ROOT / "project/reference-ts"
PACKAGES = (("starter-js", "react-starter-v1.zip"), ("starter-ts", "typescript-starter-v1.zip"))
ARCHIVES = ROOT.parent / "phase2/apps/web/public/projects"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ids(rows):
    return [row["id"] for row in rows]


def load_module(name):
    return json.loads((ROOT / "content" / f"{name}.json").read_text(encoding="utf-8-sig"))


def compose():
    previous = BASE.read_bytes()
    require(hashlib.sha256(previous).hexdigest() == BASE_SHA256, "The reviewed Phase 9 bundle changed")
    bundle = json.loads(previous)
    sample, graph = bundle["sample"], bundle["graph"]
    sample.update(releaseId=RELEASE, title="منهج البرمجة والبيانات والواجهات المتكاملة",
                  intro="ابدأ بالأساسيات أو SQL، ثم اختر Python أو الويب. "
                  "جهّز مشروعات JavaScript وابنِ كتالوج React، وأضف TypeScript أو اربط خدمة Backend عندما يناسب هدفك.")
    graph["releaseId"] = RELEASE
    terms = {entry["term"] for entry in sample["glossary"]}
    modules = []
    for name, prefix, count in MODULES:
        module = load_module(name)
        modules.append(module)
        expected = [f"{prefix}-{number:02}" for number in range(1, count + 1)]
        require(ids(module["lessons"]) == ids(module["graphLessons"]) == module["track"]["lessonIds"] == expected,
                f"Lesson order differs for {name}")
        require(module["goal"]["id"] == module["track"]["id"] == name, f"Goal and track differ for {name}")
        require(module["goal"]["skillIds"] == ids(module["skills"]), f"Goal skills differ for {name}")
        require(all(len(lesson["exercises"]) >= 2 for lesson in module["lessons"]), f"Incomplete exercises for {name}")
        require(module["project"]["lessonId"] == expected[-1], f"Missing capstone for {name}")
        sample["lessons"].extend(module["lessons"])
        sample["tracks"].append(module["track"])
        sample["projects"].append(module["project"])
        graph["skills"].extend(module["skills"])
        graph["lessons"].extend(module["graphLessons"])
        graph["goals"].append(module["goal"])
        graph["goals"].extend(module.get("extraGoals", []))
        bundle["codeLab"].extend({key: value for key, value in lab.items() if key != "solution"}
                                 for lab in module["labs"])
        for entry in module["glossary"]:
            if entry["term"] not in terms:
                sample["glossary"].append(entry)
                terms.add(entry["term"])
    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"], graph["lessons"],
                 graph["goals"], bundle["codeLab"], exercises):
        require(len(set(ids(rows))) == len(rows), "Duplicate Phase 10 identifiers")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 1_048_576, "The curriculum exceeds the API import limit")
    return payload, modules, len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])


def source_files(folder):
    require(folder.is_dir(), f"Missing authored project: {folder.name}")
    excluded = {".local", "node_modules", "dist", "coverage", "test-results", "playwright-report", ".git"}
    suffixes = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".html", ".css", ".md", ".txt"}
    files = {}
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part in excluded for part in relative.parts) or not path.is_file():
            continue
        require(not path.is_symlink(), "Project source must not contain symbolic links")
        if path.name not in {".gitignore", ".env.example"} and path.suffix not in suffixes:
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        files[relative.as_posix()] = path.read_bytes()
    require(all(name in files for name in ("README.md", "package.json", "package-lock.json", "LICENSES.md")),
            f"Incomplete package, instructions or license record for {folder.name}")
    return files


def package_starters(check=False):
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    for folder, filename in PACKAGES:
        expected = source_files(ROOT / "project" / folder)
        path = ARCHIVES / filename
        if check:
            with zipfile.ZipFile(path) as archive:
                require(len(archive.namelist()) == len(expected) and set(archive.namelist()) == set(expected),
                        f"Unexpected starter archive entries for {filename}")
                require(all(archive.read(name) == data for name, data in expected.items()),
                        f"The starter archive differs from authored files: {filename}")
        else:
            with zipfile.ZipFile(path, "w") as archive:
                for name, data in sorted(expected.items()):
                    entry = zipfile.ZipInfo(name, date_time=(2026, 11, 18, 0, 0, 0))
                    archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)
        print(f"PASSED: {filename} matches {len(expected)} authored source files")


def normalize(value):
    return value.replace("\r\n", "\n").removesuffix("\n")


def run(command, cwd, data=""):
    result = subprocess.run([str(argument) for argument in command], cwd=cwd, input=data.encode("utf-8"),
                            capture_output=True, timeout=40)
    return result, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace")


def javascript_cases(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"]) if example["language"] != "text"}
    checks = {(case["lessonId"], case["index"]): case for case in module["exampleChecks"]}
    require(len(checks) == len(module["exampleChecks"]) and examples.keys() == checks.keys(),
            f"Snippet check coverage differs for {module['track']['id']}")
    for key, example in examples.items():
        case = checks[key]
        require(example["language"] == "javascript", "Phase 10 console examples must be JavaScript")
        yield f"{key[0]} example {key[1] + 1}", example["code"], case["input"], case["output"]
    for lab in module["labs"]:
        require(lab["language"] == "javascript", "Phase 10 console labs must use JavaScript")
        cases = [{"input": lab["sampleInput"], "expectedOutput": lab["sampleOutput"]}, *lab["hiddenTests"]]
        require(len({case["input"] for case in cases}) == len(cases), f"Repeated lab input in {lab['id']}")
        require(any(normalize(case["expectedOutput"]) != normalize(lab["sampleOutput"]) for case in lab["hiddenTests"]),
                f"Lab {lab['id']} would accept a printed sample")
        for index, case in enumerate(cases, 1):
            yield f"{lab['id']} case {index}", lab["solution"], case["input"], case["expectedOutput"]


def verify_javascript(modules):
    node = shutil.which("node")
    require(node, "Node.js is required")
    count = 0
    for module in modules:
        for label, code, data, output in javascript_cases(module):
            result, stdout, stderr = run([node, "-e", code], ROOT, data)
            require(result.returncode == 0 and not stderr, f"{label}: {stderr}")
            require(normalize(stdout) == normalize(output), f"{label}: stdout mismatch")
            count += 1
    print(f"PASSED: {count} JavaScript console and lab cases")


def verify_modules(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"])}
    checks = module["multiFileChecks"]
    for case in checks:
        with tempfile.TemporaryDirectory(prefix="nexora-js-modules-") as directory:
            folder = Path(directory)
            (folder / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            for file in case["files"]:
                path = folder / file["path"]
                require(path.resolve().is_relative_to(folder.resolve()) and not path.exists(), "Unsafe module check path")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(examples[file["lessonId"], file["index"]]["code"], encoding="utf-8")
            require((folder / case["entry"]).is_file(), "Module entry is missing")
            result, stdout, stderr = run([shutil.which("node"), case["entry"]], folder, case["input"])
            require(result.returncode == 0 and not stderr, f"{case['id']}: {stderr}")
            require(normalize(stdout) == normalize(case["output"]), f"{case['id']}: module output mismatch")
    print(f"PASSED: {len(checks)} exact multi-file ESM examples")


def compiler(project):
    candidate = project / "node_modules/typescript/lib/tsc.js"
    if not candidate.is_file():
        candidate = TS_PROJECT / "node_modules/typescript/lib/tsc.js"
    require(candidate.is_file(), "Install the pinned compiler in reference-ts before checking examples")
    return [shutil.which("node"), candidate]


def verify_jsx(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"]) if example["language"] == "text"}
    checks = module["jsxChecks"]
    require([(case["lessonId"], case["index"]) for case in checks] == list(examples),
            "Every displayed JSX example must have a render check")
    compile_command = compiler(JS_PROJECT)
    scratch = JS_PROJECT / ".local"
    scratch.mkdir(exist_ok=True)
    for case in checks:
        key = case["lessonId"], case["index"]
        with tempfile.TemporaryDirectory(prefix="jsx-check-", dir=scratch) as directory:
            folder = Path(directory)
            source = folder / "example.jsx"
            source.write_text(examples[key]["code"], encoding="utf-8")
            result, stdout, stderr = run([*compile_command, source, "--ignoreConfig", "--outDir", folder / "compiled", "--allowJs",
                                         "--checkJs", "false", "--jsx", "react-jsx", "--module", "esnext",
                                         "--moduleResolution", "bundler", "--target", "es2020", "--skipLibCheck"], JS_PROJECT)
            require(result.returncode == 0, f"{key}: JSX compile failed: {stdout}{stderr}")
            code = ("import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';"
                    "const {default: Component}=await import(process.argv[1]);"
                    "console.log(renderToStaticMarkup(React.createElement(Component,JSON.parse(process.argv[2]))));")
            result, stdout, stderr = run([shutil.which("node"), "--input-type=module", "-e", code,
                                         (folder / "compiled/example.js").as_uri(), json.dumps(case["props"])], JS_PROJECT)
            require(result.returncode == 0 and not stderr, f"{key}: React render failed: {stderr}")
            require(normalize(stdout) == case["expectedHtml"], f"{key}: initial React markup mismatch: {stdout}")
    print(f"PASSED: {len(checks)} compiled JSX examples and initial React rendering")


def verify_types(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"]) if example["language"] == "text"}
    checks = module["typeChecks"]
    require([(case["lessonId"], case["index"]) for case in checks] == list(examples),
            "Every displayed TypeScript example must have a compiler check")
    compile_command = compiler(TS_PROJECT)
    scratch = TS_PROJECT / ".local"
    scratch.mkdir(exist_ok=True)
    for case in checks:
        key = case["lessonId"], case["index"]
        with tempfile.TemporaryDirectory(prefix="types-check-", dir=scratch) as directory:
            folder = Path(directory)
            source = folder / case["filename"]
            require(source.parent == folder and source.suffix in {".ts", ".tsx"}, "Unexpected type-check filename")
            source.write_text(examples[key]["code"], encoding="utf-8")
            result, stdout, stderr = run([*compile_command, source, "--ignoreConfig", "--outDir", folder / "compiled", "--strict",
                                         "--jsx", "react-jsx", "--module", "esnext", "--moduleResolution", "bundler",
                                         "--target", "es2020", "--lib", "es2020,dom", "--skipLibCheck", "--pretty", "false"], TS_PROJECT)
            actual = sorted(int(code) for code in re.findall(r"error TS(\d+):", stdout + stderr))
            expected = sorted(case["expectedErrors"])
            require(actual == expected and (result.returncode == 0) == (not expected),
                    f"{case['id']}: compiler diagnostics differ: {stdout}{stderr}")
            if "output" in case:
                require(not expected, "An invalid TypeScript example must not be run")
                result, stdout, stderr = run([shutil.which("node"), folder / "compiled" / source.with_suffix(".js").name], TS_PROJECT)
                require(result.returncode == 0 and not stderr, f"{case['id']}: compiled example failed: {stderr}")
                require(normalize(stdout) == normalize(case["output"]), f"{case['id']}: compiled example output differs")
    print(f"PASSED: {len(checks)} positive and negative TypeScript compile checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify all authored example checks and starter archives")
    args = parser.parse_args()
    payload, modules, lessons, exercises, goals, labs = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "The curriculum differs from its authored source")
        verify_javascript(modules)
        verify_modules(modules[0])
        verify_jsx(modules[1])
        verify_types(modules[2])
    else:
        BUNDLE.parent.mkdir(parents=True, exist_ok=True)
        BUNDLE.write_bytes(payload)
    package_starters(check=args.check)
    print(f"{RELEASE}: {lessons} lessons, {exercises} graded exercises, {goals} paths, {labs} labs")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        sys.exit(f"Phase 10 curriculum check failed: {error}")
