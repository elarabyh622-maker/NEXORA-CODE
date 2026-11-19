"""Verify the reviewed Phase 13 release against a disposable PostgreSQL cluster."""

import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
OLD, NEW = "phase12-ar-v1", "phase13-ar-v1"
GOAL, CAPSTONE = "machine-learning", "mlproject-01"
STARTER = "ml-sales"
ZIP_NAME = f"{STARTER}-starter-v1.zip"
DOWNLOAD = f"/projects/{ZIP_NAME}"
PRIOR_USER = "phase13_review_prior"
LEARNER_USER = "phase13_review_learner"
ADMIN_USER = "phase13_review_admin"

# Load the existing disposable PostgreSQL and HTTP helpers without changing older checks.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("phase12_check_release", WORKSPACE / "phase12/check-release.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
Client = fixture.Client
call = fixture.call
check_private_fields = fixture.check_private_fields
check_zip = fixture.check_zip
lesson_range = fixture.lesson_range
register = fixture.register
release_snapshot = fixture.release_snapshot
require = fixture.require


def check_upgrade(guest, prior, access, publish, sql):
    require(call(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 12 starts active")
    access("grant", PRIOR_USER, goalId="applied-data")
    old_plan = call(prior, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "applied-data"}, status=201)
    old_content = call(prior, "GET", f"/content/{OLD}")
    old_snapshot = release_snapshot(sql, OLD)
    require(old_snapshot and old_plan["releaseId"] == OLD, "Phase 12 plan and release exist")

    publish()
    new_snapshot = release_snapshot(sql, NEW)
    require(new_snapshot, "Phase 13 exists after publication")
    audit_count = sql("SELECT count(*) FROM public.audit;")
    publish()
    require(release_snapshot(sql, NEW) == new_snapshot, "Repeat publication preserves the Phase 13 row")
    require(sql("SELECT count(*) FROM public.audit;") == audit_count, "Repeat publication writes no audit event")
    require(release_snapshot(sql, OLD) == old_snapshot, "Publication preserves the Phase 12 row and audit count")
    require(call(prior, "GET", "/me/plan") == old_plan, "Phase 13 preserves the saved Phase 12 plan")
    require(call(prior, "GET", f"/content/{OLD}") == old_content, "Phase 12 content remains accessible and identical")
    check_zip(prior, STARTER, 403)
    print("PASSED: Phase 12 to Phase 13 publication, repeat publication and saved Phase 12 plan", flush=True)


def check_inventory(guest, admin, sql):
    catalog = call(guest, "GET", "/catalog")
    goals = catalog["goals"]
    require(catalog["activeReleaseId"] == NEW and len(goals) == 20 and GOAL in {goal["id"] for goal in goals},
            "The public catalog includes machine-learning among 20 goals in Phase 13")
    content = call(admin, "GET", f"/content/{NEW}")
    lessons = content["sample"]["lessons"]
    require(len(lessons) == 139, "The release contains 139 lessons")
    require(sum(len(lesson["exercises"]) for lesson in lessons) == 391, "The release contains 391 exercises")
    require(int(sql(f"""
        SELECT jsonb_array_length(bundle->'codeLab') FROM public.content_releases WHERE release_id = '{NEW}';
    """)) == 48, "The release contains 48 lab definitions")
    check_private_fields(content, "complete content")
    print("PASSED: 139 lessons, 391 graded exercises, 20 goals and 48 published labs", flush=True)


def check_prices(guest, admin, learner):
    def prices(offers):
        return {offer["goalId"]: (offer["price"], offer["currency"]) for offer in offers}

    endpoint = "/admin/access/offers"
    call(learner, "PUT", f"{endpoint}/{GOAL}", {"price": 1, "currency": "EGP"}, status=403)
    existing = prices(call(admin, "GET", endpoint))
    require(GOAL not in existing, "Phase 13 publishes no preset machine-learning price")
    call(admin, "PUT", f"{endpoint}/applied-data", {"price": 75, "currency": "EGP"})
    expected = {**existing, "applied-data": (75, "EGP")}
    for value in (90, 104.5):
        call(admin, "PUT", f"{endpoint}/{GOAL}", {"price": value, "currency": "EGP"})
        expected[GOAL] = (value, "EGP")
        require(prices(call(admin, "GET", endpoint)) == expected, "The admin reads independent goal prices")
        require(prices(call(guest, "GET", "/catalog")["offers"]) == expected, "The public reads independent goal prices")
    print("PASSED: independent admin-managed machine-learning and applied-data prices", flush=True)


def check_scope(learner, expected_lessons, expected_goals):
    content = call(learner, "GET", f"/content/{NEW}")
    sample = content["sample"]
    require({lesson["id"] for lesson in sample["lessons"]} == set(expected_lessons), "Exact scoped lessons")
    require([goal["id"] for goal in content["graph"]["goals"]] == expected_goals, "Exact scoped goals")
    downloads = {project["download"] for project in sample["projects"] if "download" in project}
    require(downloads == {DOWNLOAD}, "The purchased scope includes exactly the machine-learning ZIP link")
    check_private_fields(content, "scoped content")
    check_private_fields(call(learner, "GET", f"/content/{NEW}/lessons/{CAPSTONE}"), CAPSTONE)
    check_zip(learner, STARTER, 200)
    check_zip(learner, "applied-data", 403)
    call(learner, "GET", f"/content/{NEW}/lessons/sql-01", status=403)
    call(learner, "GET", f"/content/{NEW}/lessons/applied-01", status=403)


def check_access(guest, learner, access):
    goal_request = {"releaseId": NEW, "goalId": GOAL}
    capstone_url = f"/content/{NEW}/lessons/{CAPSTONE}"
    lab_url = f"/lab/exercises/{NEW}/mleval-01"
    expected = []
    for prefix, count in (
        ("core", 12), ("py", 12), ("data", 8), ("pd", 5), ("stat", 5),
        ("mlprep", 4), ("mlmod", 4), ("mleval", 4),
    ):
        expected.extend(lesson_range(prefix, count))
    expected.append(CAPSTONE)

    call(guest, "GET", f"/content/{NEW}", status=401)
    call(learner, "GET", f"/content/{NEW}", status=403)
    check_zip(guest, STARTER, 401)
    check_zip(learner, STARTER, 403)
    access("grant", LEARNER_USER, goalId=GOAL)
    preview = call(learner, "POST", "/plan-previews", goal_request)
    require([step["lessonId"] for step in preview["steps"]] == expected and not preview["uncoveredSkillIds"],
            "The machine-learning plan includes exactly 55 lessons in prerequisite order")
    check_scope(learner, expected, [GOAL])
    labs = call(learner, "GET", lab_url)
    require([(lab["id"], lab["language"]) for lab in labs["exercises"]] == [("mleval-01-lab", "python")],
            "The MAE lab exposes its public Python metadata")
    check_private_fields(labs, "MAE lab metadata")
    access("revoke", LEARNER_USER, goalId=GOAL)
    call(learner, "GET", capstone_url, status=403)
    call(learner, "POST", "/plan-previews", goal_request, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: exact 55-lesson plan, lab redaction, goal download isolation and revocation", flush=True)

    access("grant", LEARNER_USER, lessonId=CAPSTONE)
    check_scope(learner, [CAPSTONE], [])
    call(learner, "GET", lab_url, status=403)
    call(learner, "POST", "/plan-previews", goal_request, status=403)
    access("revoke", LEARNER_USER, lessonId=CAPSTONE)
    call(learner, "GET", capstone_url, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: single-lesson grant, ZIP scope and revocation, and learner answer redaction", flush=True)


def check_journey(origin, command, publish, sql):
    guest = Client(origin)
    admin = register(origin, ADMIN_USER)
    learner = register(origin, LEARNER_USER)
    prior = register(origin, PRIOR_USER)
    command("--promote-admin", ADMIN_USER)
    admin.refresh_csrf()

    def access(action, name, **scope):
        call(admin, "POST", f"/admin/access/{action}", {"userName": name, **scope})

    check_upgrade(guest, prior, access, publish, sql)
    check_inventory(guest, admin, sql)
    check_prices(guest, admin, learner)
    check_access(guest, learner, access)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--postgres-bin", required=True, type=Path, help="PostgreSQL binaries at an ASCII Windows path")
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/curriculum.json")
    parser.add_argument("--bundle-sha256", required=True)
    args = parser.parse_args()
    assembly = args.assembly.resolve(strict=True)
    bundle = args.bundle.resolve(strict=True)
    digest = args.bundle_sha256.lower()
    require(hashlib.sha256(bundle.read_bytes()).hexdigest() == digest, "Phase 13 bundle differs from the reviewed digest")

    previous = [*fixture.PREVIOUS, WORKSPACE / "phase12/dist/curriculum.json"]
    require(all(path.is_file() for path in previous), "A predecessor curriculum is missing")
    require((fixture.PROJECTS / ZIP_NAME).is_file(), "The reviewed starter ZIP is missing")
    pg = args.postgres_bin.absolute()
    for name in ("initdb.exe", "postgres.exe", "pg_isready.exe", "psql.exe", "pg_ctl.exe"):
        require((pg / name).is_file(), f"Missing PostgreSQL binary {name}")

    fixture.PREVIOUS = previous
    fixture.ZIP_NAME = ZIP_NAME
    fixture.check_journey = check_journey
    fixture.run_isolated(assembly, pg, bundle, digest)


if __name__ == "__main__":
    main()
