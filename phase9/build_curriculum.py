"""Build and verify the Phase 9 Python, SQL writing, Backend and Full Stack curriculum."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase8/dist/curriculum.json"
BASE_SHA256 = "e6287e0aac68d5e2b5b9be933ee4dc408e8cd6bfb3b1d8c83d97dd735e62b82a"
RELEASE = "phase9-ar-v1"
MODULES = (("python-projects", "pyproj", 3), ("sql-write", "sql-write", 4),
           ("backend", "backend", 7), ("fullstack", "fullstack", 2))
BUNDLE = ROOT / "dist/curriculum.json"
STARTER = ROOT / "project/starter"
ARCHIVE = ROOT.parent / "phase2/apps/web/public/projects/backend-starter-v1.zip"
PROJECT_PYTHON = ROOT / "project/.local/venv/Scripts/python.exe"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ids(rows):
    return [row["id"] for row in rows]


def load_module(name):
    return json.loads((ROOT / "content" / f"{name}.json").read_text(encoding="utf-8-sig"))


def compose():
    previous = BASE.read_bytes()
    require(hashlib.sha256(previous).hexdigest() == BASE_SHA256, "The reviewed Phase 8 bundle changed")
    bundle = json.loads(previous)
    sample, graph = bundle["sample"], bundle["graph"]
    sample.update(releaseId=RELEASE, title="منهج البرمجة والبيانات وتطبيقات الويب المتكاملة",
                  intro="اختر الأساسيات أو SQL ثم تقدم في Python أو الويب. جهّز مشروع Python، "
                  "وتعلم كتابة البيانات وبناء Backend مع FastAPI. بعد مسار الويب اربط الخدمة بواجهة كتالوج متكامل.")
    graph["releaseId"] = RELEASE
    terms = {item["term"] for item in sample["glossary"]}
    modules = []
    for name, prefix, count in MODULES:
        module = load_module(name)
        modules.append(module)
        lesson_ids = [f"{prefix}-{number:02}" for number in range(1, count + 1)]
        lessons, skills = module["lessons"], module["skills"]
        require(ids(lessons) == ids(module["graphLessons"]) == module["track"]["lessonIds"] == lesson_ids,
                f"Lesson order differs for {name}")
        require(module["track"]["id"] == module["goal"]["id"] == name,
                f"Goal or track identifiers differ for {name}")
        require(module["goal"]["skillIds"] == ids(skills), f"Goal skill list differs for {name}")
        require(all(len(lesson["exercises"]) >= 2 for lesson in lessons), f"Incomplete exercises in {name}")
        require(module["project"]["lessonId"] == lesson_ids[-1], f"Missing capstone in {name}")
        sample["lessons"].extend(lessons)
        sample["tracks"].append(module["track"])
        sample["projects"].append(module["project"])
        graph["skills"].extend(skills)
        graph["lessons"].extend(module["graphLessons"])
        graph["goals"].append(module["goal"])
        bundle["codeLab"].extend({key: value for key, value in lab.items() if key != "solution"}
                                 for lab in module["labs"])
        for item in module["glossary"]:
            if item["term"] not in terms:
                sample["glossary"].append(item)
                terms.add(item["term"])
    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"], graph["lessons"],
                 graph["goals"], bundle["codeLab"], exercises):
        require(len(set(ids(rows))) == len(rows), "Duplicate identifiers in Phase 9")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 1_048_576, "Curriculum exceeds the import limit")
    return payload, modules, len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])


def starter_files():
    require(STARTER.is_dir(), "The authored Backend starter is missing")
    items = {}
    for path in sorted(STARTER.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(STARTER)
        require(not path.is_symlink(), "A starter file must not be a symbolic link")
        if any(part in {".local", ".venv", "__pycache__", ".pytest_cache", "data", ".git"}
               for part in relative.parts):
            continue
        if path.suffix not in {".py", ".md", ".txt", ".html", ".css", ".js", ".toml"} and path.name != ".gitignore":
            continue
        items[relative.as_posix()] = path.read_bytes()
    require("README.md" in items and any(name.endswith("app.py") for name in items),
            "Incomplete Backend starter")
    license_file = ROOT / "project/LICENSES.md"
    require(license_file.is_file(), "The project dependency license record is missing")
    items["LICENSES.md"] = license_file.read_bytes()
    require(not any("reference" in Path(name).parts for name in items), "Reference solutions entered starter package")
    return items


def package_starter(check=False):
    expected = starter_files()
    if check:
        with zipfile.ZipFile(ARCHIVE) as archive:
            require(set(archive.namelist()) == set(expected), "Starter package file list changed")
            require(all(archive.read(name) == content for name, content in expected.items()),
                    "Starter package differs from authored files")
    else:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ARCHIVE, "w") as archive:
            for name, content in sorted(expected.items()):
                entry = zipfile.ZipInfo(name, date_time=(2026, 11, 18, 0, 0, 0))
                archive.writestr(entry, content, compress_type=zipfile.ZIP_DEFLATED)
    print(f"PASSED: starter package includes {len(expected)} authored files")


def normalize(value):
    return value.replace("\r\n", "\n").removesuffix("\n")


def executions(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"]) if example["language"] != "text"}
    checks = {(case["lessonId"], case["index"]): case for case in module["exampleChecks"]}
    require(len(checks) == len(module["exampleChecks"]) and examples.keys() == checks.keys(),
            f"Example check coverage differs for {module['track']['id']}")
    for key, example in examples.items():
        case = checks[key]
        yield f"{key[0]} example {key[1] + 1}", example["language"], example["code"], case["input"], case["output"]
    for lab in module["labs"]:
        cases = [{"input": lab["sampleInput"], "expectedOutput": lab["sampleOutput"]}, *lab["hiddenTests"]]
        require(len({case["input"] for case in cases}) == len(cases), f"Repeated lab input in {lab['id']}")
        require(any(normalize(case["expectedOutput"]) != normalize(lab["sampleOutput"]) for case in lab["hiddenTests"]),
                f"Lab {lab['id']} could be passed by printing the sample output")
        for index, case in enumerate(cases, 1):
            yield f"{lab['id']} case {index}", lab["language"], lab["solution"], case["input"], case["expectedOutput"]


def verify_examples(modules, interpreter):
    require(interpreter.is_file(), "Prepare the Backend project environment before checking FastAPI examples")
    node = shutil.which("node")
    require(node, "Node.js is required to check the frontend example")
    counts = {"python": 0, "javascript": 0}
    for module in modules:
        for label, language, code, value, output in executions(module):
            if language == "python":
                command = [str(interpreter), "-I", "-X", "utf8", "-B", "-c", code]
            elif language == "javascript":
                command = [node, "-e", code]
            else:
                raise ValueError(f"Unknown execution language at {label}")
            result = subprocess.run(command, input=value.encode("utf-8"), capture_output=True, timeout=30, cwd=ROOT)
            require(result.returncode == 0 and not result.stderr,
                    f"{label}: {result.stderr.decode('utf-8', 'replace')}")
            require(normalize(result.stdout.decode("utf-8")) == normalize(output), f"{label}: stdout mismatch")
            counts[language] += 1
    print(f"PASSED: {counts['python']} Python and {counts['javascript']} JavaScript cases")


def verify_sql(module):
    cases = module["sqlChecks"]
    require({case["lessonId"] for case in cases} == set(ids(module["lessons"])),
            "Every SQL writing lesson must have an execution check")
    require(len(set(ids(cases))) == len(cases), "Duplicate SQL check identifier")
    for case in cases:
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
            connection.executescript(module["sqlSetup"])
            require(connection.execute("PRAGMA foreign_keys").fetchone() == (1,), "Foreign keys must be active")
            if case.get("setupSql"):
                connection.executescript(case["setupSql"])
            for step in case.get("statements", []):
                try:
                    connection.execute(step["sql"])
                except sqlite3.Error as error:
                    require(step.get("expectedError") and step["expectedError"] in str(error),
                            f"{case['id']}: unexpected SQL error")
                else:
                    require(not step.get("expectedError"), f"{case['id']}: expected SQL rejection did not occur")
            actual = [list(row) for row in connection.execute(case["query"])]
            require(actual == case["expectedRows"], f"{case['id']}: unexpected rows after SQL changes")
    print(f"PASSED: {len(cases)} SQLite writing, constraint and transaction cases")


def sql_statements(code):
    statements = []
    buffer = ""
    for character in code:
        buffer += character
        if character == ";" and sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    remaining = "\n".join(line for line in buffer.splitlines() if not line.lstrip().startswith("--")).strip()
    require(not remaining, "Displayed SQL contains an incomplete statement")
    return statements


def verify_displayed_sql(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"])}
    checks = module["sqlDisplayChecks"]
    keys = [(case["lessonId"], case["index"]) for case in checks]
    require(keys == list(examples), "SQL display checks must cover every example exactly once in lesson order")
    require(examples[keys[0]]["code"] == module["sqlSetup"], "SQL setup differs from the learner's first example")
    with tempfile.TemporaryDirectory(prefix="nexora-sql-writing-") as directory:
        database = Path(directory) / "training.sqlite3"
        with closing(sqlite3.connect(database, isolation_level=None)) as connection:
            for key, case in zip(keys, checks):
                statements = sql_statements(examples[key]["code"])
                require(len(statements) == len(case["steps"]), f"SQL example {key}: step coverage changed")
                for statement, expected in zip(statements, case["steps"]):
                    try:
                        cursor = connection.execute(statement)
                    except sqlite3.Error as error:
                        require(expected.get("error") and expected["error"] in str(error),
                                f"SQL example {key}: unexpected rejection")
                    else:
                        require(not expected.get("error"), f"SQL example {key}: expected rejection did not occur")
                        if cursor.description:
                            rows = [list(row) for row in cursor]
                            require(rows == expected.get("rows"), f"SQL example {key}: displayed result differs")
                        else:
                            require("rows" not in expected, f"SQL example {key}: statement no longer returns rows")
                require(connection.in_transaction == case["inTransaction"], f"SQL example {key}: transaction state differs")
        with closing(sqlite3.connect(database)) as connection:
            final = module["sqlDisplayFinal"]
            rows = [list(row) for row in connection.execute(final["query"])]
            require(rows == final["expectedRows"], "SQL training data did not persist after reopening the file")
    print(f"PASSED: {len(checks)} exact displayed SQL examples and file persistence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Run authored examples and verify the built release")
    parser.add_argument("--project-python", type=Path, default=PROJECT_PYTHON,
                        help="Python interpreter with the pinned Backend project dependencies")
    args = parser.parse_args()
    payload, modules, lessons, exercises, goals, labs = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "The curriculum differs from its authored source. Rebuild it.")
        verify_sql(modules[1])
        verify_displayed_sql(modules[1])
        verify_examples(modules, args.project_python.resolve())
    else:
        BUNDLE.parent.mkdir(parents=True, exist_ok=True)
        BUNDLE.write_bytes(payload)
    package_starter(check=args.check)
    print(f"{RELEASE}: {lessons} lessons, {exercises} graded exercises, {goals} paths, {labs} labs")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        sys.exit(f"Phase 9 curriculum check failed: {error}")
