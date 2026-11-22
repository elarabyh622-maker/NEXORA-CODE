"""Build the cumulative C# release and verify its authored examples and project ZIP."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase13/dist/curriculum.json"
BASE_DIGEST = "772e3e44cafb95b6f9ab44ce85ef558f703ab101392a69b9d132a18df3b35171"
BUNDLE = ROOT / "dist/curriculum.json"
RELEASE = "phase14-ar-v1"
GOAL = "csharp"
CAPSTONE = "csproject-01"
ARCHIVE = "csharp-inventory-starter-v1.zip"
MODULES = ("basics", "programming", "application")
LESSON_IDS = [f"csharp-{module}-{number:02d}" for module in MODULES for number in range(1, 5)] + [CAPSTONE]
TOTALS = (152, 430, 21, 48)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Reviewed Phase 13 bundle changed")
    bundle = json.loads(original)
    sample, graph = bundle["sample"], bundle["graph"]
    sample["releaseId"] = RELEASE
    graph["releaseId"] = RELEASE
    glossary = {entry["term"] for entry in sample["glossary"]}
    foundations = json.loads((ROOT / "content/foundations.json").read_bytes())
    general_lessons = {lesson["id"]: lesson for lesson in sample["lessons"] if lesson["id"].startswith("core-")}
    for override in foundations["lessons"]:
        lesson = general_lessons[override["id"]]
        for section in override.get("sectionOverrides", []):
            lesson["sections"][section["index"]].update({key: value for key, value in section.items() if key != "index"})
        lesson["sections"].extend(override["sections"])
        lesson["examples"].extend(override["examples"])
        exercises = {exercise["id"]: exercise for exercise in lesson["exercises"]}
        for changes in override["exercises"]:
            exercise = exercises[changes["id"]]
            require(changes.keys() <= {"id", "prompt", "options", "language", "code", "hints", "explanation"},
                    f"{exercise['id']}: a foundation wording edit must preserve grading fields")
            if "options" in changes:
                require([option["id"] for option in changes["options"]] == [option["id"] for option in exercise["options"]],
                        f"{exercise['id']}: a foundation wording edit must preserve answer option IDs")
            exercise.update(changes)
    checks = list(foundations["exampleChecks"])
    for module in MODULES:
        content = json.loads((ROOT / f"content/{module}.json").read_bytes())
        expected = [f"csharp-{module}-{number:02d}" for number in range(1, 5)]
        require([lesson["id"] for lesson in content["lessons"]] == expected, f"{module}: lesson order")
        require([lesson["id"] for lesson in content["graphLessons"]] == expected, f"{module}: graph order")
        require(len(content["skills"]) == len(expected), f"{module}: skill count")
        require(not content["labs"], f"{module}: the C# examples run locally")
        sample["lessons"].extend(content["lessons"])
        graph["lessons"].extend(content["graphLessons"])
        graph["skills"].extend(content["skills"])
        checks.extend(content["exampleChecks"])
        for entry in content["glossary"]:
            if entry["term"] not in glossary:
                sample["glossary"].append(entry)
                glossary.add(entry["term"])

    capstone = json.loads((ROOT / "content/project.json").read_bytes())
    lesson, skill, project = capstone["lesson"], capstone["skill"], capstone["project"]
    require(lesson["id"] == project["lessonId"] == CAPSTONE, "Inventory project lesson mismatch")
    require(project["download"] == f"/projects/{ARCHIVE}", "Inventory project ZIP mismatch")
    sample["lessons"].append(lesson)
    graph["lessons"].append({key: lesson[key] for key in ("id", "title", "why", "skillIds")})
    graph["skills"].append(skill)
    sample["projects"].append(project)
    checks.extend(capstone["exampleChecks"])

    title = "أساسيات C# و.NET ومشروع المخزون"
    sample["tracks"].append({"id": GOAL, "title": title, "lessonIds": LESSON_IDS})
    graph["goals"].append({
        "id": GOAL, "title": title, "status": "sample", "skillIds": [skill["id"]],
        "description": "ابدأ من الصفر مع C# و.NET، ثم ابنِ تطبيق كونسول يدير مخزونًا ويحفظ بياناته في JSON.",
    })

    added = {lesson["id"]: lesson for lesson in sample["lessons"][-len(LESSON_IDS):]}
    require(all(len(lesson["exercises"]) == 3 for lesson in added.values()), "Expected three exercises per lesson")
    examples = {(lesson_id, index): example for lesson_id, lesson in (general_lessons | added).items()
                for index, example in enumerate(lesson["examples"]) if example["language"] == "csharp"}
    cases = {(check["lessonId"], check["index"], check["input"]) for check in checks}
    require(len(cases) == len(checks) and {(lesson, index) for lesson, index, _ in cases} == set(examples),
            "Each C# example needs execution checks with distinct inputs")
    require(set(LESSON_IDS).issubset(lesson_id for lesson_id, _ in examples), "Every C# lesson needs a runnable example")

    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"],
                 graph["lessons"], graph["goals"], bundle["codeLab"], exercises):
        require(len({row["id"] for row in rows}) == len(rows), "Duplicate authoring IDs")
    require((len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])) == TOTALS,
            "Unexpected release totals")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 2 * 1024 * 1024, "Bundle exceeds the local import limit")
    return payload, examples, checks


def verify_examples(examples, checks):
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
               DOTNET_CLI_UI_LANGUAGE="en-US")
    with tempfile.TemporaryDirectory(prefix="nexora-csharp-") as scratch:
        scratch = Path(scratch)
        (scratch / "NuGet.Config").write_text(
            '<configuration><packageSources><clear /></packageSources></configuration>\n', encoding="utf-8")
        def compile_example(item):
            (lesson_id, example_index), example = item
            directory = scratch / f"{lesson_id}-{example_index}"
            directory.mkdir()
            (directory / "Program.cs").write_text(example["code"], encoding="utf-8")
            (directory / "Example.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>'
                '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
                '</PropertyGroup></Project>\n', encoding="utf-8")
            result = subprocess.run(["dotnet", "build", "--nologo", "-o", "build"], cwd=directory,
                                    capture_output=True, encoding="utf-8", env=env, timeout=60)
            require(result.returncode == 0, f"{lesson_id}/{example_index}: compilation failed\n{result.stdout}{result.stderr}")
            return (lesson_id, example_index), directory / "build/Example.dll"

        with ThreadPoolExecutor(max_workers=3) as workers:
            assemblies = dict(workers.map(compile_example, examples.items()))
        for case_number, check in enumerate(checks, 1):
            key = check["lessonId"], check["index"]
            directory = scratch / f"case-{case_number:02d}"
            directory.mkdir()
            result = subprocess.run(["dotnet", assemblies[key]], cwd=directory,
                                    input=check["input"], capture_output=True, encoding="utf-8", env=env, timeout=60)
            require(result.returncode == 0, f"{key}: execution failed\n{result.stdout}{result.stderr}")
            require(result.stdout == check["output"], f"{key}: expected {check['output']!r}, got {result.stdout!r}")
    print(f"PASSED: {len(examples)} .NET examples passed {len(checks)} execution cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify examples and the generated artifacts")
    args = parser.parse_args()
    payload, examples, checks = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Built release differs from authored files")
        verify_examples(examples, checks)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    runpy.run_path(str(ROOT / "project/package_starter.py"))["package_starter"](args.check)
    print(f"Phase 14: 152 lessons, 430 exercises, 21 goals, 48 labs ({len(payload):,} bytes)")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
