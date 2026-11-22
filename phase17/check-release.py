"""Verify the Phase 17 upgrade, plan and access on disposable PostgreSQL."""

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
previous = runpy.run_path(str(ROOT.parent / "phase16/check-release.py"))
fixture = previous["fixture"]
call, register, require = fixture.call, fixture.register, fixture.require
check_zip, check_private_fields = fixture.check_zip, fixture.check_private_fields
OLD, NEW = previous["NEW"], authoring["RELEASE"]
GOAL, CAPSTONE = authoring["GOAL"], authoring["CAPSTONE"]
ZIP_NAME, LESSONS = authoring["ARCHIVE"], authoring["LESSON_IDS"]
STARTER = ZIP_NAME.removesuffix("-starter-v1.zip")
PREDECESSORS = [*previous["PREDECESSORS"], authoring["BASE"]]
CONTENT = f"/content/{NEW}"


def verify_upgrade(guest, prior, access, publish, sql):
    require(call(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 16 starts active")
    access("grant", "phase17_prior", goalId="cpp")
    plan = call(prior, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "cpp"}, status=201)
    content = call(prior, "GET", f"/content/{OLD}")
    old_row = fixture.release_snapshot(sql, OLD)
    publish()
    new_row = fixture.release_snapshot(sql, NEW)
    audit_count = sql("SELECT count(*) FROM public.audit;")
    publish()
    require(new_row and fixture.release_snapshot(sql, NEW) == new_row, "Repeated publication preserves the release")
    require(sql("SELECT count(*) FROM public.audit;") == audit_count, "Repeated publication keeps the audit count")
    require(old_row and fixture.release_snapshot(sql, OLD) == old_row, "The Phase 16 row remains unchanged")
    require(call(prior, "GET", "/me/plan") == plan, "The existing C++ plan remains readable")
    require(call(prior, "GET", f"/content/{OLD}") == content, "The existing C++ content remains unchanged")
    check_zip(prior, STARTER, 403)
    print("PASSED: Phase 16 plan survives the upgrade and publication is idempotent", flush=True)


def verify_catalog(guest, admin, sql):
    catalog = call(guest, "GET", "/catalog")
    require(catalog["activeReleaseId"] == NEW and catalog["accessRequired"], "Phase 17 is commercially active")
    require(len(catalog["goals"]) == 24 and GOAL in {goal["id"] for goal in catalog["goals"]}, "24 goals including Java")
    require(GOAL not in {offer["goalId"] for offer in catalog["offers"]}, "No preset Java price")
    content = call(admin, "GET", CONTENT)
    lessons = content["sample"]["lessons"]
    require(len(lessons) == 185 and sum(len(lesson["exercises"]) for lesson in lessons) == 529, "Release totals")
    require(int(sql(f"SELECT jsonb_array_length(bundle->'codeLab') FROM public.content_releases WHERE release_id='{NEW}';"))
            == 48, "The existing 48 labs remain present")
    check_private_fields(content, "Phase 17 release")
    print("PASSED: release totals, active catalog and no preset price", flush=True)


def verify_scope(learner, lesson_ids, goal_ids):
    content = call(learner, "GET", CONTENT)
    require({lesson["id"] for lesson in content["sample"]["lessons"]} == set(lesson_ids), "Exact authorized lesson scope")
    require([goal["id"] for goal in content["graph"]["goals"]] == goal_ids, "Exact authorized goal scope")
    require({project.get("download") for project in content["sample"]["projects"]} == {f"/projects/{ZIP_NAME}"}, "One authorized ZIP")
    check_private_fields(content, "scoped Java content")
    overview = call(learner, "GET", CONTENT + "?view=overview")
    require({lesson["id"] for lesson in overview["sample"]["lessons"]} == set(lesson_ids), "Overview preserves scope")
    capstone = next(lesson for lesson in overview["sample"]["lessons"] if lesson["id"] == CAPSTONE)
    require("java" in capstone["exampleLanguages"] and "exercises" not in capstone, "Overview lists Java without exercise bodies")
    lesson = call(learner, "GET", f"{CONTENT}/lessons/{CAPSTONE}")
    require(any(example["language"] == "java" for example in lesson["examples"]), "The local Java example is visible")
    check_private_fields(lesson, CAPSTONE)
    check_zip(learner, STARTER, 200)
    check_zip(learner, "cpp-expenses", 403)


def verify_access(guest, learner, access, authored):
    name = "phase17_learner"
    request = {"releaseId": NEW, "goalId": GOAL}
    capstone = f"{CONTENT}/lessons/{CAPSTONE}"

    def plan():
        result = call(learner, "POST", "/plan-previews", request)
        require(not result["uncoveredSkillIds"], "All prerequisites are covered")
        return [step["lessonId"] for step in result["steps"]]

    def grade(lesson_id, exercise, answer):
        return call(learner, "POST", "/practice/attempts", {
            "releaseId": NEW, "lessonId": lesson_id, "exerciseId": exercise["id"], "answer": answer,
            "hintsUsed": 0, "idempotencyKey": secrets.token_hex(16),
        })["correct"]

    check_zip(guest, STARTER, 401)
    check_zip(learner, STARTER, 403)
    call(learner, "GET", capstone, status=403)
    access("grant", name, goalId=GOAL)
    beginner = ["core-01", *LESSONS]
    require(plan() == beginner, "13-step beginner plan with no other language prerequisite")
    verify_scope(learner, beginner, [GOAL])
    call(learner, "GET", f"{CONTENT}/lessons/cpp-project-01", status=403)
    require(not call(learner, "GET", f"/lab/exercises/{NEW}/{CAPSTONE}")["exercises"], "No online Java lab is advertised")
    for exercise in authored["core-01"]["exercises"]:
        require(grade("core-01", exercise, exercise["acceptedAnswers"][0]), "Foundation answer graded correctly")
    require(plan() == LESSONS, "12 steps after the shared foundation is demonstrated")
    access("revoke", name, goalId=GOAL)
    call(learner, "POST", "/plan-previews", request, status=403)
    check_zip(learner, STARTER, 403)
    access("grant", name, lessonId=LESSONS[0])
    check_zip(learner, STARTER, 403)
    access("revoke", name, lessonId=LESSONS[0])
    access("grant", name, lessonId=CAPSTONE)
    verify_scope(learner, [CAPSTONE], [])
    for exercise in authored[CAPSTONE]["exercises"]:
        require(not grade(CAPSTONE, exercise, "wrong-response"), "An incorrect exercise answer is rejected")
        require(grade(CAPSTONE, exercise, exercise["acceptedAnswers"][0]), "A correct exercise answer is accepted")
    access("revoke", name, lessonId=CAPSTONE)
    call(learner, "GET", capstone, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: 13/12-step plans, Java overview, grading, private ZIP and revocation", flush=True)


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
    require(hashlib.sha256(payload).hexdigest() == digest, "Phase 17 bundle differs from the reviewed digest")
    lessons = {lesson["id"]: lesson for lesson in json.loads(payload)["sample"]["lessons"]}

    def check_journey(origin, command, publish, sql):
        guest = fixture.Client(origin)
        admin = register(origin, "phase17_admin")
        learner = register(origin, "phase17_learner")
        prior = register(origin, "phase17_prior")
        command("--promote-admin", "phase17_admin")
        admin.refresh_csrf()

        def access(action, name, **scope):
            call(admin, "POST", f"/admin/access/{action}", {"userName": name, **scope})

        verify_upgrade(guest, prior, access, publish, sql)
        verify_catalog(guest, admin, sql)
        verify_access(guest, learner, access, lessons)

    fixture.PREVIOUS = PREDECESSORS
    fixture.ZIP_NAME = ZIP_NAME
    fixture.check_journey = check_journey
    fixture.run_isolated(assembly, args.postgres_bin.absolute(), bundle, digest)


if __name__ == "__main__":
    main()
