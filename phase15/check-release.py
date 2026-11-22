"""Verify Phase 15 publication and the Codex track on disposable PostgreSQL."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import secrets
import sys


ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
authoring = runpy.run_path(str(ROOT / "build_curriculum.py"))
prior_checks = runpy.run_path(str(ROOT.parent / "phase14/check-release.py"))
fixture = prior_checks["fixture"]
Client, call, register, require = fixture.Client, fixture.call, fixture.register, fixture.require
check_zip, check_private_fields = fixture.check_zip, fixture.check_private_fields
OLD, NEW = prior_checks["NEW"], authoring["RELEASE"]
GOAL, CAPSTONE = authoring["GOAL"], authoring["CAPSTONE"]
ZIP_NAME = authoring["ARCHIVE"]
STARTER = ZIP_NAME.removesuffix("-starter-v1.zip")
LESSONS = authoring["LESSON_IDS"]
PREDECESSORS = [*prior_checks["PREDECESSORS"], authoring["BASE"]]


def check_upgrade(guest, prior, access, publish, sql):
    require(call(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 14 starts active")
    access("grant", "phase15_prior", goalId="csharp")
    old_plan = call(prior, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "csharp"}, status=201)
    old_content = call(prior, "GET", f"/content/{OLD}")
    old_snapshot = fixture.release_snapshot(sql, OLD)
    publish()
    new_snapshot = fixture.release_snapshot(sql, NEW)
    audit_count = sql("SELECT count(*) FROM public.audit;")
    publish()
    require(new_snapshot and fixture.release_snapshot(sql, NEW) == new_snapshot, "Repeated publication keeps the new release row")
    require(sql("SELECT count(*) FROM public.audit;") == audit_count, "Repeated publication adds no audit event")
    require(old_snapshot and fixture.release_snapshot(sql, OLD) == old_snapshot, "Phase 14 row is unchanged")
    require(call(prior, "GET", "/me/plan") == old_plan, "The Phase 14 plan remains readable")
    require(call(prior, "GET", f"/content/{OLD}") == old_content, "The Phase 14 paid content is unchanged")
    check_zip(prior, STARTER, 403)
    print("PASSED: Phase 14 plan survives publication and Phase 15 publication is idempotent", flush=True)


def check_catalog(guest, admin, sql):
    catalog = call(guest, "GET", "/catalog")
    require(catalog["activeReleaseId"] == NEW and catalog["accessRequired"], "Phase 15 is active in commercial mode")
    require(len(catalog["goals"]) == 22 and GOAL in {goal["id"] for goal in catalog["goals"]}, "22 goals including Codex")
    require(GOAL not in {offer["goalId"] for offer in catalog["offers"]}, "The new track has no preset price")
    content = call(admin, "GET", f"/content/{NEW}")
    lessons = content["sample"]["lessons"]
    require(len(lessons) == 161 and sum(len(lesson["exercises"]) for lesson in lessons) == 457, "Release totals")
    require(int(sql(f"SELECT jsonb_array_length(bundle->'codeLab') FROM public.content_releases WHERE release_id='{NEW}';"))
            == 48, "Existing labs remain available")
    check_private_fields(content, "Phase 15 content")
    print("PASSED: active catalog, published totals, no default price and no embedded answers", flush=True)


def check_scope(learner, lessons, goals):
    content = call(learner, "GET", f"/content/{NEW}")
    sample = content["sample"]
    require({item["id"] for item in sample["lessons"]} == set(lessons), "Exact authorized lesson scope")
    require([item["id"] for item in content["graph"]["goals"]] == goals, "Exact authorized goal scope")
    require({item.get("download") for item in sample["projects"]} == {f"/projects/{ZIP_NAME}"}, "Exactly the Codex ZIP is offered")
    check_private_fields(content, "scoped Codex content")
    overview = call(learner, "GET", f"/content/{NEW}?view=overview")
    require({item["id"] for item in overview["sample"]["lessons"]} == set(lessons), "Overview preserves scope")
    require(all("exercises" not in item for item in overview["sample"]["lessons"]), "Overview carries lesson metadata only")
    lesson = call(learner, "GET", f"/content/{NEW}/lessons/{CAPSTONE}")
    check_private_fields(lesson, CAPSTONE)
    require(lesson["examples"] and all(example["language"] == "text" for example in lesson["examples"]), "Codex prompts stay readable")
    check_zip(learner, STARTER, 200)
    check_zip(learner, "csharp-inventory", 403)


def check_access(guest, learner, access, lessons):
    user = "phase15_learner"
    lesson_url = f"/content/{NEW}/lessons/{CAPSTONE}"
    plan_request = {"releaseId": NEW, "goalId": GOAL}

    def preview():
        plan = call(learner, "POST", "/plan-previews", plan_request)
        require(not plan["uncoveredSkillIds"], "The plan covers all prerequisites")
        return [step["lessonId"] for step in plan["steps"]]

    check_zip(guest, STARTER, 401)
    check_zip(learner, STARTER, 403)
    call(learner, "GET", lesson_url, status=403)
    access("grant", user, goalId=GOAL)
    beginner = ["core-01", *LESSONS]
    require(preview() == beginner, "The complete beginner plan has 10 steps")
    check_scope(learner, beginner, [GOAL])
    require(not call(learner, "GET", f"/lab/exercises/{NEW}/{CAPSTONE}")["exercises"], "Local Codex project has no hosted lab")
    for exercise in lessons["core-01"]["exercises"]:
        require(grade(learner, "core-01", exercise, exercise["acceptedAnswers"][0]), "Foundation answer graded correctly")
    require(preview() == LESSONS, "Practicing the shared foundation leaves the 9 Codex lessons")
    access("revoke", user, goalId=GOAL)
    call(learner, "POST", "/plan-previews", plan_request, status=403)
    check_zip(learner, STARTER, 403)
    access("grant", user, lessonId=LESSONS[0])
    check_zip(learner, STARTER, 403)
    access("revoke", user, lessonId=LESSONS[0])
    access("grant", user, lessonId=CAPSTONE)
    check_scope(learner, [CAPSTONE], [])
    call(learner, "POST", "/plan-previews", plan_request, status=403)
    for exercise in lessons[CAPSTONE]["exercises"]:
        require(not grade(learner, CAPSTONE, exercise, "wrong-response"), "Incorrect answer rejected")
        require(grade(learner, CAPSTONE, exercise, exercise["acceptedAnswers"][0]), "Correct answer accepted")
    access("revoke", user, lessonId=CAPSTONE)
    call(learner, "GET", lesson_url, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: 10/9-step plans, scoped content, grading, private ZIP and revocation", flush=True)


def grade(learner, lesson_id, exercise, value):
    result = call(learner, "POST", "/practice/attempts", {
        "releaseId": NEW, "lessonId": lesson_id, "exerciseId": exercise["id"],
        "answer": value, "hintsUsed": 0, "idempotencyKey": secrets.token_hex(16),
    })
    return result["correct"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=authoring["BUNDLE"])
    parser.add_argument("--bundle-sha256", required=True)
    args = parser.parse_args()
    assembly, bundle = args.assembly.resolve(strict=True), args.bundle.resolve(strict=True)
    payload = bundle.read_bytes()
    digest = args.bundle_sha256.lower()
    require(hashlib.sha256(payload).hexdigest() == digest, "Phase 15 bundle differs from the reviewed digest")
    lessons = {lesson["id"]: lesson for lesson in json.loads(payload)["sample"]["lessons"]}

    def check_journey(origin, command, publish, sql):
        guest = Client(origin)
        admin = register(origin, "phase15_admin")
        learner = register(origin, "phase15_learner")
        prior = register(origin, "phase15_prior")
        command("--promote-admin", "phase15_admin")
        admin.refresh_csrf()

        def access(action, name, **scope):
            call(admin, "POST", f"/admin/access/{action}", {"userName": name, **scope})

        check_upgrade(guest, prior, access, publish, sql)
        check_catalog(guest, admin, sql)
        check_access(guest, learner, access, lessons)

    fixture.PREVIOUS = PREDECESSORS
    fixture.ZIP_NAME = ZIP_NAME
    fixture.check_journey = check_journey
    fixture.run_isolated(assembly, args.postgres_bin.absolute(), bundle, digest)


if __name__ == "__main__":
    main()
