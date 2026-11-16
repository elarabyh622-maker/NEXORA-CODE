"""Smoke test an already-published Phase 4 release on the dedicated test database.

This starts and stops only its own staged API process. It creates a synthetic learner,
submits practice and real runner assessments, and retains those test records in
masar_phase2_tests. Publication is a separate explicit maintenance operation.
"""
import argparse
import io
import json
from pathlib import Path
import secrets
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase3"))
from test_code_lab_http import (Client, configured_runner, expect, finish, register,
                                require, send_run, submission, test_api)

BASE = "http://127.0.0.1:5182"
RELEASE = "phase4-ar-v1"
OLD = "phase1-ar-v1"


def contains_forbidden(value):
    if isinstance(value, dict):
        return any(key.lower() in {"acceptedanswers", "hiddentests", "solution", "expectedoutput"}
                   or contains_forbidden(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_forbidden(item) for item in value)
    return False


def smoke(api, content_root):
    private = json.loads((ROOT / "phase4/content/web.json").read_text(encoding="utf-8"))
    lesson = private["lessons"][0]
    exercise = lesson["exercises"][0]
    lab = next(item for item in private["labs"] if item["id"] == "web-lab-greet")
    config = configured_runner()
    guest = Client(BASE)
    with test_api(api, BASE, config, content_root):
        guest.refresh_csrf()
        status, catalog, _ = guest.request("GET", "/api/v1/catalog")
        expect(status, 200, "catalog")
        require(catalog["activeReleaseId"] == RELEASE, "Phase 4 must already be the active published release")
        published = {row["releaseId"] for row in catalog["releases"] if row["status"] == "published"}
        require({RELEASE, OLD} <= published, "both Phase 4 and Phase 1 remain published")
        for release in (RELEASE, OLD):
            status, content, _ = guest.request("GET", f"/api/v1/content/{release}")
            expect(status, 200, "public release content")
            require(not contains_forbidden(content), "public release content excludes answer keys and hidden cases")
        require(len(content["sample"]["lessons"]) == 3, "old release still has its three lessons")
        for goal, expected, forbidden in [("explore", 12, ("py.", "web.")),
                                           ("python", 24, ("web.",)),
                                           ("web", 24, ("py.",))]:
            status, plan, _ = guest.request("POST", "/api/v1/plan-previews", {"releaseId": RELEASE, "goalId": goal})
            expect(status, 200, "plan preview")
            require(len(plan["steps"]) == expected, f"{goal} plan lesson count")
            require(not plan["uncoveredSkillIds"], f"{goal} has no uncovered skills")
            skills = [skill for step in plan["steps"] for skill in step["skillIds"]]
            require(not any(skill.startswith(forbidden) for skill in skills), f"{goal} excludes other branches")
        print("PASSED: active release, retained Phase 1, public content secrecy, 12/24/24 branch plans", flush=True)

        for rel, lid in [(RELEASE, lab["lessonId"]), (OLD, "what-is-a-program")]:
            status, catalog, _ = guest.request("GET", f"/api/v1/lab/exercises/{rel}/{lid}")
            expect(status, 200, "lab catalog")
            require(catalog["available"] and catalog["exercises"] and not contains_forbidden(catalog),
                    "published lab available without private test cases")
        learner = register(BASE)
        attempt = {"releaseId": RELEASE, "lessonId": lesson["id"], "exerciseId": exercise["id"],
                   "answer": exercise["acceptedAnswers"][0], "hintsUsed": 0,
                   "idempotencyKey": secrets.token_urlsafe(20)}
        status, graded, _ = learner.request("POST", "/api/v1/practice/attempts", attempt)
        expect(status, (200, 201), "choice attempt")
        require(graded["correct"] is True, "choice evaluated correctly")
        body = {"releaseId": RELEASE, "lessonId": lab["lessonId"], "exerciseId": lab["id"],
                "mode": "assess", "code": lab["solution"], "idempotencyKey": secrets.token_urlsafe(20)}
        result = finish(learner, send_run(learner, body), real_runner=True)
        require(result["status"] == "completed" and result["verdict"] == "passed" and
                result["passedCases"] == 1 + len(lab["hiddenTests"]) and
                not result["stdout"] and not result["stderr"], "new lab passed with hidden output")
        old = finish(learner, send_run(learner, submission("assess")), real_runner=True)
        require(old["status"] == "completed" and old["verdict"] == "passed" and old["passedCases"] == 3,
                "old Phase 1 lab assessment still passes")
        status, evidence, _ = learner.request("GET", f"/api/v1/lab/evidence?releaseId={RELEASE}")
        expect(status, 200, "new lab evidence")
        require(any(row["exerciseId"] == lab["id"] and row["skillId"] == lab["skillId"] for row in evidence),
                "new lab evidence recorded")
        status, old_evidence, _ = learner.request("GET", f"/api/v1/lab/evidence?releaseId={OLD}")
        expect(status, 200, "old lab evidence")
        require(any(row["exerciseId"] == "python-greeting" for row in old_evidence), "old lab evidence recorded")
        print("PASSED: choice submission, new and old real runner assessments, evidence recorded", flush=True)

        with urllib.request.urlopen(BASE + "/projects/web-starter-v1.zip", timeout=30) as response:
            require(response.status == 200, "project ZIP response")
            raw = response.read(1_000_001)
        require(len(raw) <= 1_000_000, "project ZIP is bounded")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(set(archive.namelist()) == {"index.html", "style.css", "app.js", "README.md"}, "project ZIP file list")
            for file, key in [("index.html", "html"), ("style.css", "css")]:
                require(archive.read(file).decode("utf-8") == private["browserProject"][key], f"project {file} matches reference")
            starter = archive.read("app.js").decode("utf-8")
            readme = archive.read("README.md").decode("utf-8")
            require("#name" in starter and "#show" in starter and "textContent" in starter and
                    "اكتب هنا" in starter and starter != private["browserProject"]["js"], "project JavaScript is a learner scaffold")
            require("index.html" in readme and "app.js" in readme, "project README gives local instructions")
        print("PASSED: direct project ZIP, reference HTML/CSS and learner scaffold", flush=True)

    with test_api(api, BASE, config, content_root):
        status, after, _ = learner.request("GET", f"/api/v1/lab/evidence?releaseId={RELEASE}")
        expect(status, 200, "persisted lab evidence")
        require(after == evidence, "new lab evidence survives API restart")
        status, after_old, _ = learner.request("GET", f"/api/v1/lab/evidence?releaseId={OLD}")
        expect(status, 200, "persisted old lab evidence")
        require(after_old == old_evidence, "old lab evidence survives API restart")
        status, progress, _ = learner.request("GET", f"/api/v1/me/progress?releaseId={RELEASE}")
        expect(status, 200, "persisted choice progress")
        require(progress["solved"] >= 1 and progress["attemptsCount"] >= 1, "choice progress survives API restart")
        print("PASSED: both releases' lab evidence and choice progress persist after API restart", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api", type=Path, help="absolute path to staged Masar.Api.dll")
    parser.add_argument("--content-root", type=Path, required=True, help="staged API content root containing wwwroot")
    args = parser.parse_args()
    if not args.api.is_absolute() or not args.content_root.is_absolute():
        parser.error("api and --content-root must be absolute paths")
    smoke(args.api.resolve(strict=True), args.content_root.resolve(strict=True))
