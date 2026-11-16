"""Build the immutable Phase 4 bundle and its reviewed practice artifacts."""

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
RELEASE = "phase4-ar-v1"
MODULES = [
    ("foundations", "explore", "الأساسيات المشتركة", "افهم طريقة التفكير البرمجي وأنجز مشروعًا خوارزميًا صغيرًا."),
    ("python", "python", "Python والأتمتة", "ابدأ بالأساسيات ثم ابنِ أداة Python تعالج بيانات بسيطة."),
    ("web", "web", "مدخل تطوير الويب", "ابدأ بالأساسيات ثم ابنِ صفحة عربية تفاعلية باستخدام HTML وCSS وJavaScript."),
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def write_web_starter(project, path):
    # The learner receives editable scaffolding, while the complete project stays with the QA sources.
    starter_js = """const nameInput = document.querySelector("#name");
const message = document.querySelector("#message");

function showMessage() {
  const name = nameInput.value.trim();
  // اكتب هنا نص الترحيب عندما يوجد اسم، واطلب الاسم عند الفراغ.
  // غيّر message.textContent بدلًا من إضافة HTML من إدخال المستخدم.
}

document.querySelector("#show").addEventListener("click", showMessage);
"""
    readme = """# موقع ترحيب عربي

فك ضغط الملفات في مجلد واحد وافتح index.html في متصفحك.
أكمل معالجة زر الترحيب في app.js، ثم جرّب اسمًا عربيًا وإدخالًا فارغًا.
اختبر الصفحة على عرض ضيق واستخدم Tab وEnter للوصول إلى الزر.
راجع معايير المشروع في الدرس الأخير من مسار الويب.
"""
    files = {"index.html": project["html"], "style.css": project["css"], "app.js": starter_js, "README.md": readme}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            entry = zipfile.ZipInfo(name)
            archive.writestr(entry, text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)


def unique(rows, description):
    ids = [item["id"] for item in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate {description} identifier")


def main():
    lessons, skills, graph_lessons, tracks, goals, labs, projects, checks = ([] for _ in range(8))
    glossary = {}
    browser_project = None
    for filename, goal, title, description in MODULES:
        data = json.loads((ROOT / f"content/{filename}.json").read_text(encoding="utf-8-sig"))
        module_lessons = data["lessons"]
        if len(module_lessons) != 12 or sum(len(lesson["exercises"]) for lesson in module_lessons) < 24:
            raise ValueError(f"Incomplete lesson and exercise coverage in {filename}")
        lesson_ids = [lesson["id"] for lesson in module_lessons]
        if [lesson["id"] for lesson in data["graphLessons"]] != lesson_ids:
            raise ValueError(f"Graph and lesson order differ in {filename}")
        lessons.extend(module_lessons)
        skills.extend(data["skills"])
        graph_lessons.extend(data["graphLessons"])
        tracks.append({"id": goal, "title": title, "lessonIds": lesson_ids})
        goals.append({"id": goal, "title": title, "description": description, "status": "sample",
                      "skillIds": [skill["id"] for skill in data["skills"]]})
        labs.extend(data["labs"])
        projects.append(data["project"])
        checks.extend(data["exampleChecks"])
        for entry in data["glossary"]:
            glossary.setdefault(entry["term"], entry)
        if filename == "web":
            browser_project = data["browserProject"]
            projects[-1]["download"] = "/projects/web-starter-v1.zip"

    exercises = [exercise for lesson in lessons for exercise in lesson["exercises"]]
    for rows, name in [(lessons, "lesson"), (skills, "skill"), (exercises, "exercise"), (labs, "lab"), (projects, "project")]:
        unique(rows, name)
    expected = {(lesson["id"], index): example for lesson in lessons for index, example in enumerate(lesson["examples"])
                if example["language"] in ("python", "javascript")}
    cases = {(check["lessonId"], check["index"]): check for check in checks}
    if len(checks) != len(cases) or cases.keys() != expected.keys():
        raise ValueError(f"Example check coverage mismatch: {expected.keys() ^ cases.keys()}")
    execution = []
    for key, example in expected.items():
        case = cases[key]
        execution.append({"label": f"{key[0]} example {key[1] + 1}", "language": example["language"],
                          "code": example["code"], "input": case["input"], "output": case["output"]})
    for lab in labs:
        test_cases = [{"input": lab["sampleInput"], "expectedOutput": lab["sampleOutput"]}, *lab["hiddenTests"]]
        if len({case["input"] for case in test_cases}) != len(test_cases):
            raise ValueError(f"Duplicate input for {lab['id']}")
        for number, case in enumerate(test_cases, 1):
            execution.append({"label": f"{lab['id']} case {number}", "language": lab["language"],
                              "code": lab["solution"], "input": case["input"], "output": case["expectedOutput"]})

    bundle = {
        "sample": {"schemaVersion": 1, "releaseId": RELEASE, "title": "منهج البرمجة للمبتدئين",
                   "intro": "ابدأ بوحدات التفكير البرمجي، ثم اختر Python والأتمتة أو مدخل تطوير الويب. في نهاية كل مسار مشروع تطبّق فيه ما تعلمته.",
                   "lessons": lessons, "glossary": list(glossary.values()), "tracks": tracks, "projects": projects},
        "graph": {"schemaVersion": 1, "releaseId": RELEASE, "skills": skills, "lessons": graph_lessons, "goals": goals},
        "codeLab": [{key: value for key, value in lab.items() if key != "solution"} for lab in labs],
    }
    bundle_path = ROOT / "dist/curriculum.json"
    write_json(bundle_path, bundle)
    payload = bundle_path.read_bytes()
    if len(payload) > 1_048_576:
        raise ValueError("Bundle exceeds the application import limit")
    write_json(ROOT / ".local/execution-checks.json", execution)
    write_web_starter(browser_project, ROOT.parent / "phase2/apps/web/public/projects/web-starter-v1.zip")
    print(f"{RELEASE}: {len(lessons)} lessons, {len(exercises)} graded exercises, "
          f"{len(labs)} labs, {len(projects)} projects, {len(glossary)} glossary terms, {len(execution)} executions")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
