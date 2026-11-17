"""Build Phase 8 from the reviewed Phase 7 bundle, and verify its authored examples."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase7" / "dist" / "curriculum.json"
BASE_SHA256 = "a66ba6f564d7ce49bbab3afa7aeb7d69452589e1b68a4e315d9da807583000cc"
RELEASE = "phase8-ar-v1"
MODULES = (("sql", "sql", 6), ("web-data", "web-data", 5), ("git-workshop", "git", 5))
BUNDLE = ROOT / "dist" / "curriculum.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ids(rows):
    return [row["id"] for row in rows]


def read_module(name):
    return json.loads((ROOT / "content" / f"{name}.json").read_text(encoding="utf-8-sig"))


def compose():
    base_bytes = BASE.read_bytes()
    require(hashlib.sha256(base_bytes).hexdigest() == BASE_SHA256, "Phase 7 bundle digest changed")
    bundle = json.loads(base_bytes)
    sample, graph = bundle["sample"], bundle["graph"]
    sample.update(
        releaseId=RELEASE,
        title="منهج البرمجة والبيانات وتطوير الويب",
        intro="ابدأ بالأساسيات أو تعلم الاستعلام عن البيانات مباشرةً مع SQL. "
        "تابع مسار الويب لبناء كتالوج يتعامل مع البيانات، أو تدرب على إصلاح مشروع باستخدام Git.",
    )
    graph["releaseId"] = RELEASE
    terms = {entry["term"] for entry in sample["glossary"]}
    modules = []

    for name, prefix, count in MODULES:
        module = read_module(name)
        modules.append(module)
        lessons, skills = module["lessons"], module["skills"]
        track, goal, project = module["track"], module["goal"], module["project"]
        lesson_ids = [f"{prefix}-{number:02d}" for number in range(1, count + 1)]
        require(ids(lessons) == ids(module["graphLessons"]) == track["lessonIds"] == lesson_ids,
                f"Lesson order differs in {name}")
        require(track["id"] == goal["id"] == name and goal["skillIds"] == ids(skills),
                f"Skill or goal IDs differ in {name}")
        require(project["lessonId"] == lesson_ids[-1], f"Missing final project in {name}")
        require(all(len(lesson["exercises"]) >= 2 for lesson in lessons), f"Missing graded exercises in {name}")

        sample["lessons"].extend(lessons)
        sample["tracks"].append(track)
        sample["projects"].append(project)
        graph["skills"].extend(skills)
        graph["lessons"].extend(module["graphLessons"])
        graph["goals"].append(goal)
        bundle["codeLab"].extend({key: value for key, value in lab.items() if key != "solution"}
                                 for lab in module["labs"])
        for entry in module.get("glossary", []):
            if entry["term"] not in terms:
                sample["glossary"].append(entry)
                terms.add(entry["term"])

    exercises = [item for lesson in sample["lessons"] for item in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"], graph["lessons"],
                 graph["goals"], exercises, bundle["codeLab"]):
        require(len(set(ids(rows))) == len(rows), "Duplicate curriculum IDs")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 1_048_576, "Bundle exceeds the API import limit")
    return payload, modules, len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])


def normalize_output(text):
    return text.replace("\r\n", "\n").removesuffix("\n")


def execution_cases(module):
    examples = {(lesson["id"], index): example for lesson in module["lessons"]
                for index, example in enumerate(lesson["examples"]) if example["language"] != "text"}
    checks = {(check["lessonId"], check["index"]): check for check in module["exampleChecks"]}
    require(examples.keys() == checks.keys() and len(checks) == len(module["exampleChecks"]),
            f"Execution checks do not match all examples for {module['track']['id']}")
    for (lesson_id, index), example in examples.items():
        check = checks[lesson_id, index]
        yield f"{lesson_id} example {index + 1}", example["language"], example["code"], check["input"], check["output"]

    for lab in module["labs"]:
        tests = [{"input": lab["sampleInput"], "expectedOutput": lab["sampleOutput"]}, *lab["hiddenTests"]]
        require(len({test["input"] for test in tests}) == len(tests), f"Duplicate input for {lab['id']}")
        require(any(normalize_output(test["expectedOutput"]) != normalize_output(lab["sampleOutput"])
                    for test in lab["hiddenTests"]), f"Hidden cases must vary the output for {lab['id']}")
        for index, test in enumerate(tests, start=1):
            yield f"{lab['id']} case {index}", lab["language"], lab["solution"], test["input"], test["expectedOutput"]


def verify_executions(modules):
    node = shutil.which("node")
    require(node, "Node.js is required for JavaScript verification")
    counts = {"python": 0, "javascript": 0}
    for module in modules:
        for label, language, code, value, expected in execution_cases(module):
            if language == "python":
                command = [sys.executable, "-I", "-X", "utf8", "-B", "-c", code]
            elif language == "javascript":
                command = [node, "-e", code]
            else:
                raise ValueError(f"{label}: unexpected execution language {language}")
            # Execute only fixed examples and reference solutions authored in this repository.
            result = subprocess.run(command, cwd=ROOT, input=value.encode("utf-8"), capture_output=True, timeout=8)
            require(result.returncode == 0 and not result.stderr, f"{label}: {result.stderr.decode('utf-8', 'replace')}")
            require(normalize_output(result.stdout.decode("utf-8")) == normalize_output(expected),
                    f"{label}: stdout differs from the answer key")
            counts[language] += 1
    print(f"PASSED: {counts['python']} Python cases and {counts['javascript']} JavaScript cases")


def verify_sql(module):
    lessons = {lesson["id"]: lesson for lesson in module["lessons"]}
    cases = module["sqlChecks"]
    require({case["lessonId"] for case in cases} == lessons.keys(), "Every SQL lesson needs a checked query")
    require(len(set(ids(cases))) == len(cases), "Duplicate SQL check IDs")
    for case in cases:
        if "index" in case:
            example = lessons[case["lessonId"]]["examples"][case["index"]]
            require(example["code"] == case["query"], f"{case['id']}: query does not match the lesson example")
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(module["sqlSetup"])
            if "setupSql" in case:
                connection.executescript(case["setupSql"])
            actual = [list(row) for row in connection.execute(case["query"])]
        require(actual == case["expectedRows"], f"{case['id']}: SQLite rows differ from the answer key")
    print(f"PASSED: {len(cases)} SQLite queries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify existing bundle and run authored practice cases")
    args = parser.parse_args()
    payload, modules, lessons, exercises, goals, labs = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Bundle differs from its source. Rebuild the curriculum.")
        verify_sql(modules[0])
        verify_executions(modules)
    else:
        BUNDLE.parent.mkdir(parents=True, exist_ok=True)
        BUNDLE.write_bytes(payload)
    print(f"{RELEASE}: {lessons} lessons, {exercises} graded exercises, {goals} paths, {labs} labs")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        sys.exit(f"Curriculum check failed: {error}")
