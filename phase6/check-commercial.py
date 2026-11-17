"""Commercial acceptance using synthetic accounts in masar_phase6_tests only."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2" / "scripts"))
from http_integration import Client, expect, require

sys.path.insert(0, str(ROOT / "phase3"))
from test_code_lab_http import finish, send_run

ORIGIN = "http://127.0.0.1:5196"
API = "/api/v1"
PHASE4 = "phase4-ar-v1"
PHASE7 = "phase7-ar-v1"
PROJECT = "/projects/web-starter-v1.zip"
ACCESS = f"{API}/me/access"
ADMIN = f"{API}/admin/access"
PLAN = f"{API}/plan-previews"
RUNS = f"{API}/lab/runs"


def require_test_database(environment_key, username):
    fields = {}
    allowed = {"host", "port", "database", "username", "password",
               "timeout", "command timeout", "include error detail"}
    for part in os.environ.get(environment_key, "").strip(";").split(";"):
        key, separator, value = part.partition("=")
        key = key.strip().lower()
        require(separator and key in allowed and key not in fields, "invalid fixture connection settings")
        fields[key] = value.strip()
    require((fields.get("host"), fields.get("port"), fields.get("database"), fields.get("username"))
            == ("127.0.0.1", "55436", "masar_phase6_tests", username),
            "commercial tests require the dedicated local fixture")


def curriculum_case(release):
    if release == PHASE7:
        return "data-analysis", "data-08", "data-08-lab", "phase7/content/data-project.json", 4
    return "python", "py-02", "py-02-lab", "phase4/content/python.json", 3


def lesson_ids(prefix, count):
    return [f"{prefix}-{number:02}" for number in range(1, count + 1)]


def register(label):
    client = Client(ORIGIN)
    client.refresh_csrf()
    name = f"phase6_qa_{label}_{secrets.token_hex(6)}"
    status, data, _ = client.request("POST", f"{API}/auth/register", {
        "userName": name, "displayName": "حساب قبول تقني",
        "password": secrets.token_urlsafe(24), "role": "Admin",
    })
    expect(status, 201, "synthetic account registration")
    require(data["user"]["role"] == "Learner", "registration cannot grant admin")
    client.refresh_csrf()
    return client, name


def gate(client, status, paths):
    for path in paths:
        code, body, headers = client.request("GET", path)
        expect(code, status, path)
        if status == 403:
            require(body.get("code") == "access_required", "unpaid response code")
        require("no-store" in headers.get("Cache-Control", ""), "denial is not cacheable")


def verify_lab_budget(buyer, release, definition, case_count, evidence_path):
    submission = {
        "releaseId": release, "lessonId": definition["lessonId"], "exerciseId": definition["id"],
        "mode": "run", "code": definition["solution"], "input": definition["sampleInput"],
        "idempotencyKey": secrets.token_urlsafe(20),
    }
    trial = finish(buyer, send_run(buyer, submission), real_runner=True)
    require(trial["status"] == "completed", f"sample execution ended with {trial['status']}")
    require(trial["stdout"].strip() == definition["sampleOutput"].strip()
            and trial["verdict"] == "not_evaluated", "sample execution output without grading")
    status, evidence, _ = buyer.request("GET", evidence_path)
    expect(status, 200, "sample evidence")
    require(evidence == [], "sample execution awards no evidence")

    replay = send_run(buyer, submission)
    require(replay["id"] == trial["id"] and replay["alreadyRecorded"], "idempotent submission")
    answer = {
        "releaseId": release, "lessonId": definition["lessonId"], "exerciseId": definition["id"],
        "mode": "assess", "code": definition["solution"], "idempotencyKey": secrets.token_urlsafe(20),
    }
    assessment = finish(buyer, send_run(buyer, answer), real_runner=True)
    require(assessment["status"] == "completed" and assessment["verdict"] == "passed",
            f"assessment ended with {assessment['status']}/{assessment['verdict']}")
    require(assessment.get("passedCases") == case_count and assessment.get("totalCases") == case_count
            and not assessment["stdout"] and not assessment["stderr"], "all private cases passed")
    status, evidence, _ = buyer.request("GET", evidence_path)
    expect(status, 200, "assessment evidence")
    require([(item["skillId"], item["exerciseId"]) for item in evidence]
            == [(definition["skillId"], definition["id"])], "exact assessment evidence")

    status, error, _ = buyer.request("POST", RUNS, submission | {"idempotencyKey": secrets.token_urlsafe(20)})
    expect(status, 429, "budget reached")
    require(error.get("code") == "lab_daily_limit", "exhausted budget code")
    print(f"PASSED: real sample run and assessment {case_count}/{case_count}, evidence, replay and daily cap after reserving {case_count + 1} test units",
          flush=True)
    return assessment["id"]


def acceptance(assembly, release, lab_budget):
    require_test_database("ConnectionStrings__Masar", "masar_app")
    require_test_database("ConnectionStrings__Migration", "masar_bootstrap")
    goal, lesson, exercise, source, case_count = curriculum_case(release)
    content = f"{API}/content/{release}"
    lab = f"{API}/lab/exercises/{release}/{lesson}"
    draft = f"{API}/lab/drafts/{release}/{exercise}"
    progress = f"{API}/me/progress?releaseId={release}"
    evidence_path = f"{API}/lab/evidence?releaseId={release}"
    practice_draft = f"{API}/me/drafts/{release}/core-workspace-find"
    preview = {"releaseId": release, "goalId": goal}
    blocked_run = {"releaseId": release, "lessonId": lesson, "exerciseId": exercise, "mode": "run",
                   "code": "print(6)", "idempotencyKey": secrets.token_urlsafe(20)}
    guest = Client(ORIGIN)
    status, catalog, _ = guest.request("GET", f"{API}/catalog")
    expect(status, 200, "public catalog")
    require(catalog.get("accessRequired") is True and catalog.get("activeReleaseId") == release,
            "isolated commercial catalog")
    guest.refresh_csrf()
    require(any(cookie.name == "Masar.CommercialTest.Csrf" for cookie in guest.cookies),
            "commercial test session namespace is required")
    paid_paths = (content, f"{content}/lessons/core-01", f"{content}/lessons/{lesson}",
                  f"{API}/me/plan", progress, practice_draft, lab, draft, evidence_path, PROJECT)
    gate(guest, 401, paid_paths)
    expect(guest.request("HEAD", PROJECT)[0], 401, "guest HEAD")
    print("PASSED: commercial default denies anonymous content, learning, lab and ZIP", flush=True)

    buyer, name = register("buyer")
    other, other_name = register("other")
    staff, staff_name = register("staff")
    expect(buyer.request("GET", ACCESS)[0], 200, "query access")
    require(buyer.request("GET", ACCESS)[1] == {"required": True, "active": False}, "unpaid by default")
    gate(buyer, 403, paid_paths)
    expect(buyer.request("POST", PLAN, preview)[0], 403, "unpaid preview")
    expect(buyer.request("POST", RUNS, blocked_run)[0], 403, "unpaid execution")
    expect(buyer.request("POST", f"{ADMIN}/grant", {"userName": name})[0], 403, "learner grant denied")
    expect(buyer.request("POST", f"{ADMIN}/revoke", {"userName": other_name})[0], 403, "learner revoke denied")
    print("PASSED: registration remains Learner, unpaid denied, learner cannot manage access", flush=True)

    promoted = subprocess.run(["dotnet", str(assembly), "--promote-admin", staff_name],
                              cwd=assembly.parent, capture_output=True, timeout=20)
    require(promoted.returncode == 0, "test-only administrator bootstrap")
    staff.refresh_csrf()
    require(staff.request("GET", ACCESS)[1] == {"required": True, "active": True}, "staff access")
    expect(staff.request("POST", f"{ADMIN}/grant", {"userName": name}, csrf=False)[0], 400, "admin CSRF required")
    for _ in range(2):
        status, access, _ = staff.request("POST", f"{ADMIN}/grant", {"userName": name})
        expect(status, 200, "admin grant")
        require(access.get("active") is True, "grant state")
    require(buyer.request("GET", ACCESS)[1].get("active") is True, "grant available without login again")
    for path in (content, f"{content}/lessons/core-01", f"{content}/lessons/{lesson}", progress):
        expect(buyer.request("GET", path)[0], 200, f"entitled {path}")
    status, lab_catalog, _ = buyer.request("GET", lab)
    expect(status, 200, "entitled lab")
    require(any(item["id"] == exercise for item in lab_catalog["exercises"]), "target exercise listed")
    request = urllib.request.Request(ORIGIN + PROJECT)
    with buyer.opener.open(request, timeout=15) as response:
        require(response.read(4) == b"PK\x03\x04", "real project ZIP")
        require("no-store" in response.headers.get("Cache-Control", ""), "ZIP has no-store")
    gate(other, 403, [content, lab, evidence_path, PROJECT])
    status, plan, _ = buyer.request("POST", PLAN, preview)
    expect(status, 200, "entitled plan")
    expected = lesson_ids("core", 12) + lesson_ids("py", 12)
    if release == PHASE7:
        expected += lesson_ids("data", 8)
    require([step["lessonId"] for step in plan["steps"]] == expected, f"ordered {goal} plan ({len(expected)} lessons)")
    status, _, _ = buyer.request("PUT", draft, {"code": "print(6)", "expectedVersion": 0})
    expect(status, 200, "entitled lab draft")
    print("PASSED: admin grant and repeat, database state, authorized plan, draft, ZIP and CSRF", flush=True)

    run_id = None
    try:
        if lab_budget:
            require(lab_catalog.get("available") is True, "isolated runner enabled")
            authored = json.loads((ROOT / source).read_text(encoding="utf-8-sig"))
            definition = next(item for item in authored["labs"] if item["id"] == exercise)
            run_id = verify_lab_budget(buyer, release, definition, case_count, evidence_path)
        else:
            print(f"SKIPPED: real runner budget test (requires an empty daily test budget of {case_count + 1})", flush=True)
    finally:
        status, access, _ = staff.request("POST", f"{ADMIN}/revoke", {"userName": name})
        expect(status, 200, "admin revoke")
        require(access.get("active") is False and buyer.request("GET", ACCESS)[1].get("active") is False,
                "revoke reflected in the existing session")
        gate(buyer, 403, paid_paths)
        expect(buyer.request("PUT", draft, {"code": "print(9)", "expectedVersion": 1})[0], 403, "revoked writes")
        if run_id is not None:
            gate(buyer, 403, [f"{RUNS}/{run_id}"])
        expect(buyer.request("POST", RUNS, blocked_run)[0], 403, "revoked execution")
        expect(buyer.request("HEAD", PROJECT)[0], 403, "revoked HEAD")
        expect(buyer.request("GET", f"{API}/auth/me")[0], 200, "account stays signed in")
        print("PASSED: revocation blocks same-session requests and downloads immediately", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--release", choices=(PHASE4, PHASE7), default=PHASE4)
    parser.add_argument("--lab-budget", action="store_true",
                        help="exercise a real runner with a fresh daily limit (Phase 4: 4; Phase 7: 5)")
    arguments = parser.parse_args()
    acceptance(arguments.assembly.resolve(strict=True), arguments.release, arguments.lab_budget)
