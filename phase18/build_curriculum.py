"""Compose the Go 1.26 track and check its examples and starter archive."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase17/dist/curriculum.json"
BASE_DIGEST = "ea7ab0d56b10621d45783330df6bdb465cd54cd8ae6f96282cc553218c074355"
BUNDLE = ROOT / "dist/curriculum.json"
RELEASE = "phase18-ar-v1"
GOAL = "go"
CAPSTONE = "go-project-01"
ARCHIVE = "go-tasks-api-starter-v1.zip"
MODULES = {"basics": ("go-basics", 4), "coding": ("go-code", 4), "data": ("go-data", 3)}
LESSON_IDS = [f"{prefix}-{number:02d}" for prefix, count in MODULES.values() for number in range(1, count + 1)] + [CAPSTONE]
TOTALS = (197, 565, 25, 48)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Published Phase 17 bundle changed")
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
        require(not content["labs"], f"{module}: Go examples run locally")
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
    require(lesson["id"] == project["lessonId"] == CAPSTONE, "Go project lesson mismatch")
    require(project["download"] == f"/projects/{ARCHIVE}", "Go project ZIP mismatch")
    require(skill["id"] == "go.project", "Go project skill mismatch")
    sample["lessons"].append(lesson)
    graph["lessons"].append({key: lesson[key] for key in ("id", "title", "why", "skillIds")})
    graph["skills"].append(skill)
    sample["projects"].append(project)
    checks.extend(capstone["exampleChecks"])

    title = "أساسيات Go ومشروع API لإدارة المهام"
    sample["tracks"].append({"id": GOAL, "title": title, "lessonIds": LESSON_IDS})
    graph["goals"].append({
        "id": GOAL, "title": title, "status": "sample", "skillIds": [skill["id"]],
        "description": "تعلّم أساسيات Go 1.26 وابنِ خدمة HTTP محلية لإضافة المهام وعرضها وتحديث حالتها باستخدام JSON.",
    })

    added = sample["lessons"][-len(LESSON_IDS):]
    require(all(len(item["exercises"]) == 3 for item in added), "Every Go lesson needs three exercises")
    examples = {(item["id"], index): example["code"] for item in added
                for index, example in enumerate(item["examples"]) if example["language"] == "go"}
    cases = {(check["lessonId"], check["index"], check["input"]) for check in checks}
    require(len(cases) == len(checks) and {(lesson_id, index) for lesson_id, index, _ in cases} == set(examples),
            "Each Go example needs execution checks with distinct inputs")
    require({lesson_id for lesson_id, _ in examples} == set(LESSON_IDS), "Every Go lesson needs a compilable example")
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
    compiler = shutil.which(compiler_path or "go")
    require(compiler, "Install Go 1.26 or pass --go with the Go executable path")
    compiler = Path(compiler).resolve()
    environment = dict(os.environ, GOENV="off", GOTOOLCHAIN="local", GOWORK="off",
                       GO111MODULE="on", GOPROXY="off", GOSUMDB="off", CGO_ENABLED="0",
                       GOFLAGS="-p=2", GOMAXPROCS="2")
    for option in ("GOOS", "GOARCH", "GODEBUG"):
        environment.pop(option, None)
    version = subprocess.run([compiler, "version"], env=environment, capture_output=True,
                             encoding="utf-8", check=True, timeout=15).stdout
    match = re.search(r"\bgo1\.(\d+)\b", version)
    require(match and int(match[1]) >= 26, f"Expected Go 1.26 or newer, received {version.strip()}")

    with tempfile.TemporaryDirectory(prefix="nexora-go-", ignore_cleanup_errors=True) as scratch:
        scratch = Path(scratch)
        environment.setdefault("GOCACHE", str(scratch / "cache"))
        (scratch / "go.mod").write_text("module example/nexora-go-examples\n\ngo 1.26.0\n", encoding="utf-8")

        def compile_example(item):
            (lesson_id, index), code = item
            directory = scratch / f"{lesson_id}-{index}"
            directory.mkdir()
            source = directory / "main.go"
            source.write_text(code, encoding="utf-8")
            executable = directory / ("example.exe" if os.name == "nt" else "example")
            result = subprocess.run([compiler, "build", "-trimpath", "-o", executable, "."],
                                    cwd=directory, env=environment, capture_output=True,
                                    encoding="utf-8", errors="replace", timeout=180)
            require(result.returncode == 0, f"{lesson_id}/{index} compilation failed\n{result.stdout}{result.stderr}")
            return (lesson_id, index), executable

        with ThreadPoolExecutor(max_workers=2) as workers:
            binaries = dict(workers.map(compile_example, examples.items()))
        for number, check in enumerate(checks, 1):
            key = check["lessonId"], check["index"]
            directory = scratch / f"case-{number:02d}"
            directory.mkdir()
            result = subprocess.run([binaries[key]], cwd=directory, env=environment, input=check["input"],
                                    capture_output=True, encoding="utf-8", timeout=15)
            require(result.returncode == 0 and result.stdout == check["output"],
                    f"{key}: expected {check['output']!r}, got {result.stdout!r}\n{result.stderr}")
    if scratch.exists():
        print(f"Temporary build directory still in use: {scratch}", file=sys.stderr)
    print(f"PASSED: {len(examples)} Go 1.26 examples passed {len(checks)} execution cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify examples and generated artifacts")
    parser.add_argument("--go", help="Path to the Go executable used during --check")
    args = parser.parse_args()
    payload, examples, checks = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Built release differs from authored files")
        verify_examples(examples, checks, args.go)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    runpy.run_path(str(ROOT / "project/package_starter.py"))["package_starter"](args.check)
    print(f"Phase 18: 197 lessons, 565 exercises, 25 goals, 48 labs ({len(payload):,} bytes)")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
