"""Compose the Codex automation course on the unchanged Phase 14 release."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "phase14/dist/curriculum.json"
BASE_DIGEST = "4a56a5bd70f28b1ccb5a47b1ce603158c4c864efd6127fb63661d3258bb3bb78"
BUNDLE = ROOT / "dist/curriculum.json"
RELEASE = "phase15-ar-v1"
GOAL = "codex-automation"
CAPSTONE = "codex-project-01"
ARCHIVE = "codex-automation-starter-v1.zip"
MODULES = {"local": "codex-local", "automation": "codex-flow"}
LESSON_IDS = [f"{prefix}-{number:02d}" for prefix in MODULES.values() for number in range(1, 5)] + [CAPSTONE]
TOTALS = (161, 457, 22, 48)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compose():
    original = BASE.read_bytes()
    require(hashlib.sha256(original).hexdigest() == BASE_DIGEST, "Published Phase 14 bundle changed")
    bundle = json.loads(original)
    sample, graph = bundle["sample"], bundle["graph"]
    sample["releaseId"] = graph["releaseId"] = RELEASE
    glossary_terms = {entry["term"] for entry in sample["glossary"]}
    for module, prefix in MODULES.items():
        content = json.loads((ROOT / f"content/{module}.json").read_bytes())
        expected = [f"{prefix}-{number:02d}" for number in range(1, 5)]
        require([lesson["id"] for lesson in content["lessons"]] == expected, f"{module}: lesson order")
        require([lesson["id"] for lesson in content["graphLessons"]] == expected, f"{module}: graph order")
        require(len(content["skills"]) == len(expected), f"{module}: skill count")
        require(not content["labs"] and not content["exampleChecks"], f"{module}: local text examples only")
        sample["lessons"].extend(content["lessons"])
        graph["lessons"].extend(content["graphLessons"])
        graph["skills"].extend(content["skills"])
        for entry in content["glossary"]:
            if entry["term"] not in glossary_terms:
                sample["glossary"].append(entry)
                glossary_terms.add(entry["term"])

    capstone = json.loads((ROOT / "content/project.json").read_bytes())
    lesson, skill, project = capstone["lesson"], capstone["skill"], capstone["project"]
    require(lesson["id"] == project["lessonId"] == CAPSTONE, "Codex project lesson mismatch")
    require(project["download"] == f"/projects/{ARCHIVE}", "Codex project ZIP mismatch")
    require(skill["id"] == "codex.project" and not capstone["exampleChecks"], "Codex project scope mismatch")
    sample["lessons"].append(lesson)
    graph["lessons"].append({key: lesson[key] for key in ("id", "title", "why", "skillIds")})
    graph["skills"].append(skill)
    sample["projects"].append(project)

    title = "استخدام Codex في أتمتة المهام على Windows"
    sample["tracks"].append({"id": GOAL, "title": title, "lessonIds": LESSON_IDS})
    graph["goals"].append({
        "id": GOAL, "title": title, "status": "sample", "skillIds": [skill["id"]],
        "description": "اكتب مهمة واضحة لـCodex، نفّذها على ملفات تدريب، راجع الناتج وجهّز تقريرًا يمكن تشغيله دوريًا.",
    })

    added = sample["lessons"][-len(LESSON_IDS):]
    require(all(len(lesson["exercises"]) == 3 and lesson["examples"] and
                all(example["language"] == "text" for example in lesson["examples"]) for lesson in added),
            "Every Codex lesson needs three exercises and at least one local text example")
    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows in (sample["lessons"], sample["tracks"], sample["projects"], graph["skills"],
                 graph["lessons"], graph["goals"], bundle["codeLab"], exercises):
        require(len({row["id"] for row in rows}) == len(rows), "Duplicate authoring IDs")
    require((len(sample["lessons"]), len(exercises), len(graph["goals"]), len(bundle["codeLab"])) == TOTALS,
            "Unexpected release totals")
    payload = (json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(payload) <= 2 * 1024 * 1024, "Bundle exceeds the local import limit")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare generated artifacts to their reviewed sources")
    args = parser.parse_args()
    payload = compose()
    if args.check:
        require(BUNDLE.read_bytes() == payload, "Built release differs from authored files")
    else:
        BUNDLE.parent.mkdir(exist_ok=True)
        BUNDLE.write_bytes(payload)
    runpy.run_path(str(ROOT / "project/package_starter.py"))["package_starter"](args.check)
    print(f"Phase 15: 161 lessons, 457 exercises, 22 goals, 48 labs ({len(payload):,} bytes)")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
