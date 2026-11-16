"""Extend the reviewed Phase 4 bundle with a versioned data-analysis track."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase4" / "dist" / "curriculum.json"
BASE_HASH = "378ddc4d0405fd978efd6c2a56c8a419da73cecd553d1fef5f011e3b3d397743"
RELEASE = "phase7-ar-v1"
GOAL = "data-analysis"
TITLE = "تحليل البيانات بـPython"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def require_ids(rows, ids, name):
    if [item["id"] for item in rows] != ids:
        raise ValueError(f"Unexpected {name} identifiers or order")


def build():
    payload = BASE.read_bytes()
    if hashlib.sha256(payload).hexdigest() != BASE_HASH:
        raise ValueError("The Phase 4 bundle differs from its reviewed digest.")
    bundle = json.loads(payload)
    sample = bundle["sample"]
    graph = bundle["graph"]
    modules = [
        json.loads((ROOT / "content" / filename).read_text(encoding="utf-8-sig"))
        for filename in ("data-foundations.json", "data-project.json")
    ]
    lessons = [lesson for module in modules for lesson in module["lessons"]]
    skills = [skill for module in modules for skill in module["skills"]]
    graph_lessons = [lesson for module in modules for lesson in module["graphLessons"]]
    lesson_ids = [f"data-{number:02}" for number in range(1, 9)]
    skill_ids = ["data.csv", "data.schema", "data.clean", "data.summary", "data.groups",
                 "data.rates", "data.report", "data.project"]
    require_ids(lessons, lesson_ids, "lesson")
    require_ids(graph_lessons, lesson_ids, "graph lesson")
    require_ids(skills, skill_ids, "skill")
    for index, skill in enumerate(skills):
        expected = "py.automation" if index == 0 else skill_ids[index - 1]
        if skill["required"] != {"skill": expected}:
            raise ValueError(f"Unexpected prerequisite at {skill['id']}")
        if len(lessons[index]["exercises"]) < 2:
            raise ValueError(f"Too few exercises at {lesson_ids[index]}")
    labs = [lab for module in modules for lab in module["labs"]]
    project = modules[1]["project"]
    if (len(labs) < 4 or project["lessonId"] != lesson_ids[-1]
            or not any(lab["lessonId"] == lesson_ids[-1] for lab in labs)):
        raise ValueError("Incomplete lab and capstone coverage.")
    if any(lab["language"] != "python" for lab in labs):
        raise ValueError("The data track uses the existing Python runner.")

    checks = {}
    for module in modules:
        for check in module["exampleChecks"]:
            key = (check["lessonId"], check["index"])
            if key in checks:
                raise ValueError(f"Duplicate execution check: {key}")
            checks[key] = check
    executions = []
    for lesson in lessons:
        for index, example in enumerate(lesson["examples"]):
            if example["language"] != "python":
                continue
            check = checks.pop((lesson["id"], index))
            executions.append(dict(label=f"{lesson['id']} example {index + 1}", language="python",
                                   code=example["code"], input=check["input"], output=check["output"]))
    if checks or len(executions) < len(lessons):
        raise ValueError("Missing or unmatched Python example execution checks.")
    for lab in labs:
        cases = [dict(input=lab["sampleInput"], expectedOutput=lab["sampleOutput"]), *lab["hiddenTests"]]
        if len({case["input"] for case in cases}) != len(cases):
            raise ValueError(f"Duplicate test case in {lab['id']}")
        for index, case in enumerate(cases, start=1):
            executions.append(dict(label=f"{lab['id']} case {index}", language="python",
                                   code=lab["solution"], input=case["input"], output=case["expectedOutput"]))

    sample.update(releaseId=RELEASE, title="منهج البرمجة وتحليل البيانات",
                  intro="ابدأ بالأساسيات ثم اختر الأتمتة بـPython أو تطوير الويب. بعد Python يمكنك التخصص في تحليل البيانات وبناء تقرير من CSV.")
    graph["releaseId"] = RELEASE
    graph["skills"].extend(skills)
    graph["lessons"].extend(graph_lessons)
    graph["goals"].append(dict(id=GOAL, title=TITLE,
                               description="تعلّم قراءة CSV وتنظيفه وتجميعه ثم قدّم تقريرًا يوضح ما تقوله البيانات.",
                               status="sample", skillIds=skill_ids))
    sample["lessons"].extend(lessons)
    sample["tracks"].append(dict(id=GOAL, title=TITLE, lessonIds=lesson_ids))
    sample["projects"].append(project)
    known_terms = {entry["term"] for entry in sample["glossary"]}
    for module in modules:
        for entry in module["glossary"]:
            if entry["term"] not in known_terms:
                sample["glossary"].append(entry)
                known_terms.add(entry["term"])
    bundle["codeLab"].extend({key: value for key, value in lab.items() if key != "solution"} for lab in labs)
    for rows in (sample["lessons"], graph["skills"], graph["lessons"], graph["goals"], sample["tracks"],
                 sample["projects"], bundle["codeLab"],
                 [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]):
        ids = [item["id"] for item in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate identifier in the extended curriculum.")
    bundle_path = ROOT / "dist" / "curriculum.json"
    write_json(bundle_path, bundle)
    output = bundle_path.read_bytes()
    if len(output) > 1_048_576:
        raise ValueError("The extended curriculum exceeds the import limit.")
    write_json(ROOT / ".local" / "execution-checks.json", executions)
    print(f"{RELEASE}: {len(sample['lessons'])} lessons, {len(labs)} new labs, {len(executions)} new executions")
    print(f"SHA-256: {hashlib.sha256(output).hexdigest()}")


if __name__ == "__main__":
    build()
