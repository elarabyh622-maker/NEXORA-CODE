"""Compose the C++20 track and check its examples and starter archive."""

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
BASE = ROOT.parent / "phase15/dist/curriculum.json"
BASE_DIGEST = "76899cc306fea8b8f04e066a1642c668da4bc5d0d07a3acf1d8405f552ada2a7"
BUNDLE = ROOT / "dist/curriculum.json"
RELEASE = "phase16-ar-v1"
GOAL = "cpp"
CAPSTONE = "cpp-project-01"
ARCHIVE = "cpp-expenses-starter-v1.zip"
MODULES = {"basics": ("cpp-basics", 4), "coding": ("cpp-code", 4), "data": ("cpp-data", 3)}
LESSON_IDS = [f"{prefix}-{number:02d}" for prefix, count in MODULES.values() for number in range(1, count + 1)] + [CAPSTONE]
TOTALS = (173, 493, 23, 48)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Published Phase 15 bundle changed")
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
        require(not content["labs"], f"{module}: C++ examples run locally")
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
    require(lesson["id"] == project["lessonId"] == CAPSTONE, "C++ project lesson mismatch")
    require(project["download"] == f"/projects/{ARCHIVE}", "C++ project ZIP mismatch")
    require(skill["id"] == "cpp.project", "C++ project skill mismatch")
    sample["lessons"].append(lesson)
    graph["lessons"].append({key: lesson[key] for key in ("id", "title", "why", "skillIds")})
    graph["skills"].append(skill)
    sample["projects"].append(project)
    checks.extend(capstone["exampleChecks"])

    title = "أساسيات C++ ومشروع متتبّع المصروفات"
    sample["tracks"].append({"id": GOAL, "title": title, "lessonIds": LESSON_IDS})
    graph["goals"].append({
        "id": GOAL, "title": title, "status": "sample", "skillIds": [skill["id"]],
        "description": "ابدأ مع C++20، واكتب برنامجًا محليًا يسجّل المصروفات ويحفظها ويحسب الإجماليات حسب الفئة.",
    })

    added = sample["lessons"][-len(LESSON_IDS):]
    require(all(len(item["exercises"]) == 3 for item in added), "Every C++ lesson needs three exercises")
    examples = {(item["id"], index): example["code"] for item in added
                for index, example in enumerate(item["examples"]) if example["language"] == "cpp"}
    cases = {(check["lessonId"], check["index"], check["input"]) for check in checks}
    require(len(cases) == len(checks) and {(lesson_id, index) for lesson_id, index, _ in cases} == set(examples),
            "Each C++ example needs execution checks with distinct inputs")
    require({lesson_id for lesson_id, _ in examples} == set(LESSON_IDS), "Every C++ lesson needs a compilable example")
    exercises = [exercise for item in sample["lessons"] for exercise in item["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"],
                 graph["lessons"], graph["goals"], bundle["codeLab"], exercises):
        require(len({row["id"] for row in rows}) == len(rows), "Duplicate authoring IDs")
    require((len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])) == TOTALS,
            "Unexpected release totals")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 2 * 1024 * 1024, "Bundle exceeds the local import limit")
    return payload, examples, checks


def verify_examples(examples, checks, compiler_path):
    compiler = shutil.which(compiler_path or os.getenv("CXX") or "g++")
    require(compiler, "Pass --compiler with a C++20 compiler executable (GCC, Clang or MSVC)")
    msvc = Path(compiler).stem.lower() in {"cl", "clang-cl"}
    env = dict(os.environ, PATH=str(Path(compiler).parent) + os.pathsep + os.environ.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="nexora-cpp-") as scratch:
        scratch = Path(scratch)

        def compile_example(item):
            (lesson_id, index), code = item
            directory = scratch / f"{lesson_id}-{index}"
            directory.mkdir()
            source = directory / "example.cpp"
            source.write_text(code, encoding="utf-8")
            binary = directory / ("example.exe" if os.name == "nt" else "example")
            flags = ["/nologo", "/std:c++20", "/utf-8", "/EHsc", "/W4", "/WX", source.name, f"/Fe:{binary.name}"] if msvc else [
                "-std=c++20", "-Wall", "-Wextra", "-Wpedantic", "-Werror", source.name, "-o", binary.name,
            ]
            result = subprocess.run([compiler, *flags], cwd=directory, env=env, capture_output=True,
                                    encoding="utf-8", errors="replace", timeout=90)
            require(result.returncode == 0, f"{lesson_id}/{index} compilation failed\n{result.stdout}{result.stderr}")
            return (lesson_id, index), binary

        with ThreadPoolExecutor(max_workers=3) as workers:
            binaries = dict(workers.map(compile_example, examples.items()))
        for number, check in enumerate(checks, 1):
            key = check["lessonId"], check["index"]
            directory = scratch / f"case-{number:02d}"
            directory.mkdir()
            result = subprocess.run([binaries[key]], cwd=directory, env=env, input=check["input"],
                                    capture_output=True, encoding="utf-8", timeout=15)
            require(result.returncode == 0 and result.stdout == check["output"],
                    f"{key}: expected {check['output']!r}, got {result.stdout!r}\n{result.stderr}")
    print(f"PASSED: {len(examples)} C++20 examples passed {len(checks)} execution cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify examples and generated artifacts")
    parser.add_argument("--compiler", help="Path to the C++20 compiler executable used during --check")
    args = parser.parse_args()
    payload, examples, checks = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Built release differs from authored files")
        verify_examples(examples, checks, args.compiler)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    runpy.run_path(str(ROOT / "project/package_starter.py"))["package_starter"](args.check)
    print(f"Phase 16: 173 lessons, 493 exercises, 23 goals, 48 labs ({len(payload):,} bytes)")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
