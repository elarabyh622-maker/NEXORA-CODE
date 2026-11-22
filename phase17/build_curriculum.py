"""Compose the Java 21 track and check its examples and starter archive."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase16/dist/curriculum.json"
BASE_DIGEST = "2d8077bfcc2e9357f855e37858429b91f54be23591cf902fe3a239269417c621"
BUNDLE = ROOT / "dist/curriculum.json"
RELEASE = "phase17-ar-v1"
GOAL = "java"
CAPSTONE = "java-project-01"
ARCHIVE = "java-library-starter-v1.zip"
MODULES = {"basics": ("java-basics", 4), "coding": ("java-code", 4), "data": ("java-data", 3)}
LESSON_IDS = [f"{prefix}-{number:02d}" for prefix, count in MODULES.values() for number in range(1, count + 1)] + [CAPSTONE]
TOTALS = (185, 529, 24, 48)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Published Phase 16 bundle changed")
    bundle = json.loads(original)
    sample, graph = bundle["sample"], bundle["graph"]
    sample["releaseId"] = graph["releaseId"] = RELEASE
    glossary_terms = {entry["term"] for entry in sample["glossary"]}
    checks = []
    for module, (prefix, count) in MODULES.items():
        content = json.loads((ROOT / f"content/{module}.json").read_bytes())
        expected = [f"{prefix}-{number:02d}" for number in range(1, count + 1)]
        require([lesson["id"] for lesson in content["lessons"]] == expected, f"{module}: lesson order")
        require([lesson["id"] for lesson in content["graphLessons"]] == expected, f"{module}: graph order")
        require(len(content["skills"]) == len(expected), f"{module}: skill count")
        require(not content["labs"], f"{module}: Java examples run locally")
        sample["lessons"].extend(content["lessons"])
        graph["lessons"].extend(content["graphLessons"])
        graph["skills"].extend(content["skills"])
        checks.extend(content["exampleChecks"])
        for entry in content["glossary"]:
            if entry["term"] not in glossary_terms:
                sample["glossary"].append(entry)
                glossary_terms.add(entry["term"])

    capstone = json.loads((ROOT / "content/project.json").read_bytes())
    lesson, skill, project = capstone["lesson"], capstone["skill"], capstone["project"]
    require(lesson["id"] == project["lessonId"] == CAPSTONE, "Java project lesson mismatch")
    require(project["download"] == f"/projects/{ARCHIVE}", "Java project ZIP mismatch")
    require(skill["id"] == "java.project", "Java project skill mismatch")
    sample["lessons"].append(lesson)
    graph["lessons"].append({key: lesson[key] for key in ("id", "title", "why", "skillIds")})
    graph["skills"].append(skill)
    sample["projects"].append(project)
    checks.extend(capstone["exampleChecks"])

    title = "أساسيات Java ومشروع سجل استعارة الكتب"
    sample["tracks"].append({"id": GOAL, "title": title, "lessonIds": LESSON_IDS})
    graph["goals"].append({
        "id": GOAL, "title": title, "status": "sample", "skillIds": [skill["id"]],
        "description": "تعلّم أساسيات Java 21 وابنِ برنامجًا محليًا لتسجيل الكتب واستعارتها وإرجاعها، مع حفظ الحالة في ملف.",
    })

    added = sample["lessons"][-len(LESSON_IDS):]
    require(all(len(item["exercises"]) == 3 for item in added), "Every Java lesson needs three exercises")
    examples = {(item["id"], index): example["code"] for item in added
                for index, example in enumerate(item["examples"]) if example["language"] == "java"}
    cases = {(check["lessonId"], check["index"], check["input"]) for check in checks}
    require(len(cases) == len(checks) and {(lesson_id, index) for lesson_id, index, _ in cases} == set(examples),
            "Each Java example needs execution checks with distinct inputs")
    require({lesson_id for lesson_id, _ in examples} == set(LESSON_IDS), "Every Java lesson needs a compilable example")
    exercises = [exercise for item in sample["lessons"] for exercise in item["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"],
                 graph["lessons"], graph["goals"], bundle["codeLab"], exercises):
        require(len({row["id"] for row in rows}) == len(rows), "Duplicate authoring IDs")
    require((len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])) == TOTALS,
            "Unexpected release totals")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 2 * 1024 * 1024, "Bundle exceeds the local import limit")
    return payload, examples, checks



def verify_examples(examples, checks, jdk):
    executable_suffix = ".exe" if os.name == "nt" else ""
    compiler = str(jdk / "bin" / f"javac{executable_suffix}") if jdk else shutil.which("javac")
    require(compiler and Path(compiler).is_file(), "Install JDK 21 or pass --jdk with its installation directory")
    compiler = Path(compiler).resolve()
    runtime = compiler.with_name(f"java{executable_suffix}")
    require(runtime.is_file(), "The selected JDK has no java executable alongside javac")
    environment = os.environ.copy()
    for option in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        environment.pop(option, None)

    with tempfile.TemporaryDirectory(prefix="nexora-java-") as scratch:
        scratch = Path(scratch)

        def compile_example(item):
            (lesson_id, index), code = item
            directory = scratch / f"{lesson_id}-{index}"
            directory.mkdir()
            source = directory / "Main.java"
            source.write_text(code, encoding="utf-8")
            flags = ["-encoding", "UTF-8", "--release", "21", "-Xlint:all", "-Werror", "-d", str(directory)]
            result = subprocess.run([compiler, *flags, source], cwd=directory, env=environment,
                                    capture_output=True, encoding="utf-8", errors="replace", timeout=90)
            require(result.returncode == 0, f"{lesson_id}/{index} compilation failed\n{result.stdout}{result.stderr}")
            return (lesson_id, index), directory

        with ThreadPoolExecutor(max_workers=2) as workers:
            classes = dict(workers.map(compile_example, examples.items()))
        for number, check in enumerate(checks, 1):
            key = check["lessonId"], check["index"]
            directory = scratch / f"case-{number:02d}"
            directory.mkdir()
            result = subprocess.run([runtime, "-Dfile.encoding=UTF-8", "-cp", classes[key], "Main"],
                                    cwd=directory, env=environment, input=check["input"],
                                    capture_output=True, encoding="utf-8", timeout=20)
            require(result.returncode == 0 and result.stdout == check["output"],
                    f"{key}: expected {check['output']!r}, got {result.stdout!r}\n{result.stderr}")
    print(f"PASSED: {len(examples)} Java 21 examples passed {len(checks)} execution cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify examples and generated artifacts")
    parser.add_argument("--jdk", type=Path, help="Path to the JDK 21 installation directory used during --check")
    args = parser.parse_args()
    payload, examples, checks = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Built release differs from authored files")
        verify_examples(examples, checks, args.jdk)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    runpy.run_path(str(ROOT / "project/package_starter.py"))["package_starter"](args.check)
    print(f"Phase 17: 185 lessons, 529 exercises, 24 goals, 48 labs ({len(payload):,} bytes)")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
