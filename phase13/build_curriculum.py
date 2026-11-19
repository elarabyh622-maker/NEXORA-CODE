"""Build and check the reviewed introductory machine learning release."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import zipfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase12/dist/curriculum.json"
BASE_DIGEST = "71e7df9dffaf548b3ad6a98f60d8acc3002d4b24addb2679db0e5ed93e8d77d2"
BUNDLE = ROOT / "dist/curriculum.json"
ARCHIVE = ROOT.parent / "phase2/apps/web/public/projects/ml-sales-starter-v1.zip"
RELEASE = "phase13-ar-v1"
MODULES = {"preparation": "mlprep", "model": "mlmod", "evaluation": "mleval"}
PROJECT_FILES = (
    "LICENSES.md", "README.md", "data/weekly_sales.csv", "evaluate.py", "forecast.py",
    "models.py", "prepare.py", "requirements.txt", "test_forecast.py",
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Reviewed Phase 12 bundle changed")
    bundle = json.loads(original)
    sample, graph = bundle["sample"], bundle["graph"]
    sample.update(releaseId=RELEASE, title="منهج البرمجة وتحليل البيانات وتعلم الآلة",
                  intro="اختر هدفك وتعلّم المهارات المطلوبة له. انتقل من شرح عربي وتمارين قصيرة إلى مشروع يختبر فهمك.")
    graph["releaseId"] = RELEASE
    lesson_ids, verification = [], {}
    glossary = {entry["term"] for entry in sample["glossary"]}
    for name, prefix in MODULES.items():
        module = json.loads((ROOT / f"content/{name}.json").read_bytes())
        expected = [f"{prefix}-{index:02d}" for index in range(1, 5)]
        require([lesson["id"] for lesson in module["lessons"]] == expected, f"{name}: lesson order")
        require([lesson["id"] for lesson in module["graphLessons"]] == expected, f"{name}: graph order")
        require(len(module["skills"]) == 4, f"{name}: skill count")
        require(all(len(lesson["exercises"]) == 3 for lesson in module["lessons"]), f"{name}: exercise count")
        require(len(module["labs"]) == (1 if name == "evaluation" else 0), f"{name}: lab count")
        sample["lessons"].extend(module["lessons"])
        graph["lessons"].extend(module["graphLessons"])
        graph["skills"].extend(module["skills"])
        bundle["codeLab"].extend({key: value for key, value in lab.items() if key != "solution"}
                                 for lab in module["labs"])
        for entry in module["glossary"]:
            if entry["term"] not in glossary:
                sample["glossary"].append(entry)
                glossary.add(entry["term"])
        verification[name] = module
        lesson_ids.extend(expected)

    capstone = json.loads((ROOT / "content/project.json").read_bytes())
    lesson = capstone["lesson"]
    sample["lessons"].append(lesson)
    graph["lessons"].append({key: lesson[key] for key in ("id", "title", "why", "skillIds")})
    graph["skills"].append(capstone["skill"])
    sample["projects"].append(capstone["project"])
    verification["project"] = {"lessons": [lesson], "exampleChecks": capstone["exampleChecks"], "labs": []}
    lesson_ids.append(lesson["id"])
    title = "مدخل إلى تعلم الآلة بـPython"
    sample["tracks"].append({"id": "machine-learning", "title": title, "lessonIds": lesson_ids})
    graph["goals"].append({
        "id": "machine-learning", "title": title, "status": "sample", "skillIds": [capstone["skill"]["id"]],
        "description": "درّب أول نموذج لتوقع مبيعات متجر خيالي، وقارنه بمتوسط المبيعات واختبر خطأه على أسابيع أحدث.",
    })
    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"],
                 graph["lessons"], graph["goals"], bundle["codeLab"], exercises):
        require(len({row["id"] for row in rows}) == len(rows), "Duplicate authoring IDs")
    require((len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"]))
            == (139, 391, 20, 48), "Unexpected release totals")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 1_048_576, "Bundle exceeds the import limit")
    return payload, verification


def starter_files():
    source = ROOT / "project/reference"
    files = {name: (source / name).read_bytes() for name in PROJECT_FILES}
    expression = b'return "linear" if linear_mae < baseline_mae else "baseline"'
    require(files["forecast.py"].count(expression) == 1, "The project must have one starter exercise marker")
    files["forecast.py"] = files["forecast.py"].replace(
        expression, b'return "baseline"  # TODO: choose by the validation error and break ties')
    return files


def package_starter(check):
    files = starter_files()
    if check:
        with zipfile.ZipFile(ARCHIVE) as zipped:
            require(zipped.namelist() == list(files), "Unexpected starter members")
            require(all(zipped.read(name) == data for name, data in files.items()), "ZIP differs from starter sources")
    else:
        with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for name, contents in files.items():
                entry = zipfile.ZipInfo(name, date_time=(2026, 11, 19, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                zipped.writestr(entry, contents)
    print(f"PASSED: {ARCHIVE.name} has {len(files)} reviewed members")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify examples, labs and built artifacts")
    args = parser.parse_args()
    payload, modules = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Built release differs from authored files")
        phase12 = runpy.run_path(str(ROOT.parent / "phase12/build_curriculum.py"))
        phase12["verify_examples"](modules)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    package_starter(args.check)
    print("Phase 13: 139 lessons, 391 exercises, 20 goals, 48 labs")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
