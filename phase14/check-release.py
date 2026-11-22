"""Exercise Phase 14 publication, planning, grading and access on disposable PostgreSQL."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import secrets
import sys


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
sys.dont_write_bytecode = True
authoring = runpy.run_path(str(ROOT / "build_curriculum.py"))
previous = runpy.run_path(str(WORKSPACE / "phase13/check-release.py"))
fixture = previous["fixture"]
Client, call, register, require = fixture.Client, fixture.call, fixture.register, fixture.require
check_zip, check_private_fields = fixture.check_zip, fixture.check_private_fields
OLD, NEW = previous["NEW"], authoring["RELEASE"]
GOAL, CAPSTONE = authoring["GOAL"], authoring["CAPSTONE"]
ZIP_NAME = authoring["ARCHIVE"]
STARTER = ZIP_NAME.removesuffix("-starter-v1.zip")
NEW_LESSONS = authoring["LESSON_IDS"]
FOUNDATIONS = [f"core-{number:02d}" for number in range(1, 12)]
PREDECESSORS = [*fixture.PREVIOUS, WORKSPACE / "phase12/dist/curriculum.json", authoring["BASE"]]


def check_upgrade(guest, prior, access, publish, sql):
    require(call(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 13 starts active")
    access("grant", "phase14_prior", goalId="machine-learning")
    old_plan = call(prior, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "machine-learning"}, status=201)
    old_content = call(prior, "GET", f"/content/{OLD}")
    old_snapshot = fixture.release_snapshot(sql, OLD)
    require(old_snapshot and old_plan["releaseId"] == OLD, "Phase 13 plan and release exist")
    publish()
    current = fixture.release_snapshot(sql, NEW)
    require(current, "Phase 14 release exists")
    audit_count = sql("SELECT count(*) FROM public.audit;")
    publish()
    require(fixture.release_snapshot(sql, NEW) == current, "Repeated publication preserves the Phase 14 row")
    require(sql("SELECT count(*) FROM public.audit;") == audit_count, "Repeated publication adds no audit event")
    require(fixture.release_snapshot(sql, OLD) == old_snapshot, "Phase 13 row is unchanged")
    require(call(prior, "GET", "/me/plan") == old_plan, "The Phase 13 plan is still current for its owner")
    require(call(prior, "GET", f"/content/{OLD}") == old_content, "Prior paid content is unchanged")
    check_zip(prior, STARTER, 403)
    print("PASSED: Phase 13 upgrade, idempotent publication and preserved learner plan", flush=True)


def check_overview(client, full):
    expected_lessons = [
        {**{key: lesson[key] for key in ("id", "title", "summary", "minutes")},
         "exampleLanguages": list(dict.fromkeys(example["language"] for example in lesson["examples"]))}
        for lesson in full["sample"]["lessons"]
    ]
    expected = {**full, "sample": {**full["sample"], "lessons": expected_lessons}}
    path = f"/api/v1/content/{NEW}?view=overview"
    status, overview, headers = fixture.checks.request_after_rate_limit(lambda: client.request("GET", path))
    require(status == 200 and overview == expected, "Overview preserves scope and metadata and excludes lesson bodies")
    require(headers.get("Cache-Control") == "no-store", "Overview remains private")


def check_catalog(guest, admin, learner, sql, overview=False):
    catalog = call(guest, "GET", "/catalog")
    require(catalog["activeReleaseId"] == NEW and catalog["accessRequired"], "Phase 14 commercial catalog")
    require(len(catalog["goals"]) == 21 and GOAL in {goal["id"] for goal in catalog["goals"]}, "21 goals including C#")
    content = call(admin, "GET", f"/content/{NEW}")
    lessons = content["sample"]["lessons"]
    require(len(lessons) == 152 and sum(len(lesson["exercises"]) for lesson in lessons) == 430,
            "Published lesson and exercise counts")
    require(int(sql(f"SELECT jsonb_array_length(bundle->'codeLab') FROM public.content_releases WHERE release_id='{NEW}';"))
            == 48, "All existing labs remain published")
    check_private_fields(content, "full release presentation")
    if overview:
        check_overview(admin, content)
        targets = call(admin, "GET", "/admin/access/targets")
        require(targets == {
            "goals": [{"id": goal["id"], "title": goal["title"]} for goal in content["graph"]["goals"]
                      if goal["status"] == "sample"],
            "lessons": [{"id": lesson["id"], "title": lesson["title"]} for lesson in lessons],
        }, "Admin list targets match the full release and preserve order")
        call(learner, "GET", "/admin/access/targets", status=403)

    def prices(offers):
        return {offer["goalId"]: (offer["price"], offer["currency"]) for offer in offers}

    endpoint = "/admin/access/offers"
    call(learner, "PUT", f"{endpoint}/{GOAL}", {"price": 10, "currency": "EGP"}, status=403)
    initial = prices(call(admin, "GET", endpoint))
    require(GOAL not in initial, "C# has no preset price")
    call(admin, "PUT", f"{endpoint}/machine-learning", {"price": 75, "currency": "EGP"})
    expected = {**initial, "machine-learning": (75, "EGP")}
    for price in (90, 104.5):
        call(admin, "PUT", f"{endpoint}/{GOAL}", {"price": price, "currency": "EGP"})
        expected[GOAL] = (price, "EGP")
        require(prices(call(admin, "GET", endpoint)) == expected, "Separate goal prices in administration")
        require(prices(call(guest, "GET", "/catalog")["offers"]) == expected, "Separate goal prices in public catalog")
    print("PASSED: release counts, private answer fields and independent pricing", flush=True)


def check_scope(learner, lesson_ids, goals, overview=False):
    content = call(learner, "GET", f"/content/{NEW}")
    sample = content["sample"]
    require({lesson["id"] for lesson in sample["lessons"]} == set(lesson_ids), "Exact lesson access scope")
    require([goal["id"] for goal in content["graph"]["goals"]] == goals, "Exact goal access scope")
    downloads = {project["download"] for project in sample["projects"] if "download" in project}
    require(downloads == {f"/projects/{ZIP_NAME}"}, "The scoped content presents only the inventory ZIP")
    check_private_fields(content, "scoped C# content")
    lesson = call(learner, "GET", f"/content/{NEW}/lessons/{CAPSTONE}")
    require(any(example["language"] == "csharp" for example in lesson["examples"]), "Read-only C# example presented")
    check_private_fields(lesson, CAPSTONE)
    if overview:
        check_overview(learner, content)
        require(lesson == next(item for item in sample["lessons"] if item["id"] == CAPSTONE),
                "Individual lesson matches the same sanitized lesson in full content")
    check_zip(learner, STARTER, 200)
    check_zip(learner, "ml-sales", 403)


def answer(learner, lesson_id, exercise, value):
    return call(learner, "POST", "/practice/attempts", {
        "releaseId": NEW, "lessonId": lesson_id, "exerciseId": exercise["id"],
        "answer": value, "hintsUsed": 0, "idempotencyKey": secrets.token_hex(16),
    })["correct"]


def check_access(guest, learner, access, lessons, browser_check, overview=False):
    name = "phase14_learner"
    request = {"releaseId": NEW, "goalId": GOAL}
    capstone = f"/content/{NEW}/lessons/{CAPSTONE}"
    first_lesson = f"/content/{NEW}/lessons/{NEW_LESSONS[0]}"
    call(guest, "GET", f"/content/{NEW}", status=401)
    call(learner, "GET", f"/content/{NEW}", status=403)
    if overview:
        call(guest, "GET", f"/content/{NEW}?view=overview", status=401)
        call(learner, "GET", f"/content/{NEW}?view=overview", status=403)
    check_zip(guest, STARTER, 401)
    check_zip(learner, STARTER, 403)
    access("grant", name, goalId=GOAL)

    def plan():
        result = call(learner, "POST", "/plan-previews", request)
        require(not result["uncoveredSkillIds"], "All required skills are covered")
        return [step["lessonId"] for step in result["steps"]]

    beginner = plan()
    require([step for step in beginner if step.startswith("core-")] == FOUNDATIONS, "Ordered general foundations")
    require([step for step in beginner if not step.startswith("core-")] == NEW_LESSONS,
            "Ordered C# lessons with no other language prerequisites")
    for foundation, next_csharp in zip(("core-01", "core-05", "core-06", "core-07", "core-08", "core-10", "core-11"),
                                      (0, 1, 2, 3, 4, 5, 11)):
        require(beginner.index(foundation) < beginner.index(NEW_LESSONS[next_csharp]), "Prerequisite before C# application")
    check_scope(learner, beginner, [GOAL], overview)
    call(learner, "GET", f"/content/{NEW}/lessons/py-01", status=403)
    labs = call(learner, "GET", f"/lab/exercises/{NEW}/{CAPSTONE}")
    require(not labs["exercises"], "No online C# runner exercise is advertised")
    if browser_check:
        browser_check(learner)

    for lesson_id in FOUNDATIONS:
        for exercise in lessons[lesson_id]["exercises"]:
            require(answer(learner, lesson_id, exercise, exercise["acceptedAnswers"][0]), "Foundation answer graded correctly")
    require(plan() == NEW_LESSONS, "Proven general skills leave exactly the 13 C# lessons")
    access("revoke", name, goalId=GOAL)
    call(learner, "GET", capstone, status=403)
    call(learner, "POST", "/plan-previews", request, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: 24-step beginner plan, 13-step practice-based plan, scoped ZIP and goal revocation", flush=True)

    access("grant", name, lessonId=NEW_LESSONS[0])
    call(learner, "GET", first_lesson)
    call(learner, "GET", capstone, status=403)
    check_zip(learner, STARTER, 403)
    access("revoke", name, lessonId=NEW_LESSONS[0])
    access("grant", name, lessonId=CAPSTONE)
    check_scope(learner, [CAPSTONE], [], overview)
    call(learner, "GET", first_lesson, status=403)
    call(learner, "POST", "/plan-previews", request, status=403)
    for exercise in lessons[CAPSTONE]["exercises"]:
        require(not answer(learner, CAPSTONE, exercise, "wrong_" + secrets.token_hex(8)), "Wrong answer rejected")
        require(answer(learner, CAPSTONE, exercise, exercise["acceptedAnswers"][0]), "Correct answer accepted")
    access("revoke", name, lessonId=CAPSTONE)
    call(learner, "GET", capstone, status=403)
    check_zip(learner, STARTER, 403)
    if overview:
        call(learner, "GET", f"/content/{NEW}?view=overview", status=403)
        print("PASSED: content overview parity, private response, access and admin target projection", flush=True)
    print("PASSED: single-lesson access, correct and incorrect grading, and ZIP revocation", flush=True)


def main(browser_check=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=authoring["BUNDLE"])
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--check-overview", action="store_true", help="Check overview responses and their access rules")
    args = parser.parse_args()
    assembly, bundle = args.assembly.resolve(strict=True), args.bundle.resolve(strict=True)
    payload = bundle.read_bytes()
    digest = args.bundle_sha256.lower()
    require(hashlib.sha256(payload).hexdigest() == digest, "Phase 14 bundle differs from the reviewed digest")
    lessons = {lesson["id"]: lesson for lesson in json.loads(payload)["sample"]["lessons"]}
    pg = args.postgres_bin.absolute()
    for tool in ("initdb", "postgres", "pg_isready", "psql", "pg_ctl"):
        require((pg / f"{tool}.exe").is_file(), f"Missing PostgreSQL binary: {tool}")

    def check_journey(origin, command, publish, sql):
        guest = Client(origin)
        admin = register(origin, "phase14_admin")
        learner = register(origin, "phase14_learner")
        prior = register(origin, "phase14_prior")
        command("--promote-admin", "phase14_admin")
        admin.refresh_csrf()

        def access(action, name, **scope):
            call(admin, "POST", f"/admin/access/{action}", {"userName": name, **scope})

        check_upgrade(guest, prior, access, publish, sql)
        check_catalog(guest, admin, learner, sql, args.check_overview)
        check_access(guest, learner, access, lessons, browser_check, args.check_overview)

    fixture.PREVIOUS = PREDECESSORS
    fixture.ZIP_NAME = ZIP_NAME
    fixture.check_journey = check_journey
    fixture.run_isolated(assembly, pg, bundle, digest)


if __name__ == "__main__":
    main()
