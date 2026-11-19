"""Build the reviewed applied data analysis release from Phase 11."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase11/dist/curriculum.json"
BASE_DIGEST = "9cbf77989eb597c44a6d4bf0011587a52c5a35a23c4a6b8d0792a81c7e171ef7"
BUNDLE = ROOT / "dist/curriculum.json"
ARCHIVE = ROOT.parent / "phase2/apps/web/public/projects/applied-data-starter-v1.zip"
RELEASE = "phase12-ar-v1"
MODULES = {"pandas": "pd", "stats": "stat", "sql": "ana-sql"}
PROJECT_FILES = (
    "LICENSES.md", "README.md", "clean.py", "data/products.csv", "data/sales.csv",
    "metrics.py", "queries.sql", "requirements.txt", "sales_report.py", "test_report.py",
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Reviewed Phase 11 bundle changed")
    bundle = json.loads(original)
    sample, graph = bundle["sample"], bundle["graph"]
    sample.update(releaseId=RELEASE, title="منهج البرمجة وتحليل البيانات التطبيقي",
                  intro="اختر هدفك وابدأ بالمتطلبات اللازمة له. طبّق تحليل البيانات والخوارزميات وتطوير الويب بمشروعات وتمارين عربية.")
    graph["releaseId"] = RELEASE
    lesson_ids, verification = [], {}
    glossary = {entry["term"] for entry in sample["glossary"]}
    for name, prefix in MODULES.items():
        module = json.loads((ROOT / f"content/{name}.json").read_bytes())
        expected = [f"{prefix}-{index:02d}" for index in range(1, 6)]
        require([lesson["id"] for lesson in module["lessons"]] == expected, f"{name}: lesson order")
        require([lesson["id"] for lesson in module["graphLessons"]] == expected, f"{name}: graph order")
        require(len(module["skills"]) == 5, f"{name}: skill count")
        require(all(len(lesson["exercises"]) == 3 for lesson in module["lessons"]), f"{name}: exercise count")
        require(len(module["labs"]) == (1 if name == "stats" else 0), f"{name}: lab count")
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
    title = "تحليل البيانات التطبيقي بـPython وSQL"
    sample["tracks"].append({"id": "applied-data", "title": title, "lessonIds": lesson_ids})
    graph["goals"].append({
        "id": "applied-data", "title": title, "status": "sample", "skillIds": [capstone["skill"]["id"]],
        "description": "نظّف ملفات المبيعات بـpandas وحلّلها بالإحصاء وSQLite، ثم قدّم لوحة عربية تتحقق من أرقامها.",
    })
    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"],
                 graph["lessons"], graph["goals"], bundle["codeLab"], exercises):
        require(len({row["id"] for row in rows}) == len(rows), "Duplicate authoring IDs")
    require((len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"]))
            == (126, 352, 19, 47), "Unexpected release totals")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 1_048_576, "Bundle exceeds the import limit")
    return payload, verification


def python_output(code, stdin):
    with tempfile.TemporaryDirectory(prefix="nexora-phase12-example-") as temporary:
        path = Path(temporary) / "example.py"
        path.write_text(code, encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(path)], cwd=temporary,
                                input=stdin.encode("utf-8"), capture_output=True, timeout=20)
        require(result.returncode == 0 and not result.stderr, result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("utf-8").replace("\r\n", "\n")


def sql_output(code):
    statements, fragment = [], ""
    for char in code:
        fragment += char
        if char == ";" and sqlite3.complete_statement(fragment):
            statements.append(fragment)
            fragment = ""
    require(statements and not fragment.strip(), "SQL example lacks a complete statement")
    with sqlite3.connect(":memory:") as database:
        for statement in statements[:-1]:
            database.execute(statement)
        rows = database.execute(statements[-1]).fetchall()
        return "".join(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)


def verify_examples(modules):
    examples_checked = labs_checked = 0
    for name, module in modules.items():
        examples = {(lesson["id"], index): example for lesson in module["lessons"]
                    for index, example in enumerate(lesson["examples"])}
        checked = set()
        for case in module["exampleChecks"]:
            key = case["lessonId"], case["index"]
            require(key in examples and key not in checked, f"Unknown or duplicate example check {key}")
            example = examples[key]
            output = sql_output(example["code"]) if name == "sql" else python_output(example["code"], case["input"])
            require(output == case["output"], f"{key}: expected {case['output']!r}, got {output!r}")
            checked.add(key)
        require(checked == examples.keys(), f"{name}: missing example coverage")
        examples_checked += len(checked)
        for lab in module["labs"]:
            cases = [{"input": lab["sampleInput"], "expectedOutput": lab["sampleOutput"]}] + lab["hiddenTests"]
            for case in cases:
                require(python_output(lab["solution"], case["input"]) == case["expectedOutput"],
                        f"{lab['id']}: solution output mismatch")
                labs_checked += 1
    print(f"PASSED: {examples_checked} Python/SQLite examples and {labs_checked} lab solution cases")


def package_starter(check):
    source = ROOT / "project/reference"
    files = {name: (source / name).read_bytes() for name in PROJECT_FILES}
    expression = b"LAG(revenue_piastres) OVER (ORDER BY month) AS previous_revenue_piastres"
    require(files["queries.sql"].count(expression) == 1, "The project SQL must have one starter exercise marker")
    files["queries.sql"] = files["queries.sql"].replace(
        expression, b"NULL AS previous_revenue_piastres -- TODO: calculate the previous observed revenue")
    if check:
        with zipfile.ZipFile(ARCHIVE) as zipped:
            require(zipped.namelist() == list(files), "Starter archive contents differ from the expected file list")
            require(all(zipped.read(name) == data for name, data in files.items()), "Starter archive differs from its source")
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
        verify_examples(modules)
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    package_starter(args.check)
    print("Phase 12: 126 lessons, 352 exercises, 19 goals, 47 labs")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
