"""Commercial acceptance using synthetic accounts in masar_phase6_tests only."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase2" / "scripts"))
from http_integration import Client, expect, require

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase3"))
from test_code_lab_http import finish, send_run

ORIGIN = "http://127.0.0.1:5196"
API = "/api/v1"
RELEASE = "phase4-ar-v1"
CONTENT = f"{API}/content/{RELEASE}"
PROJECT = "/projects/web-starter-v1.zip"
ACCESS = f"{API}/me/access"
ADMIN = f"{API}/admin/access"
PLAN = f"{API}/plan-previews"
LAB = f"{API}/lab/exercises/{RELEASE}/py-02"
DRAFT = f"{API}/lab/drafts/{RELEASE}/py-02-lab"
PROGRESS = f"{API}/me/progress?releaseId={RELEASE}"
ATTEMPT_DRAFT = f"{API}/me/drafts/{RELEASE}/core-workspace-find"


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


def acceptance(assembly, lab_budget):
    connection = os.environ.get("ConnectionStrings__Migration", "")
    fields = dict(part.split("=", 1) for part in connection.split(";") if "=" in part)
    require(fields.get("Database") == "masar_phase6_tests" and fields.get("Host") == "127.0.0.1",
            "test maintenance context must point to masar_phase6_tests")
    guest = Client(ORIGIN)
    status, catalog, _ = guest.request("GET", f"{API}/catalog")
    expect(status, 200, "public catalog")
    require(catalog.get("accessRequired") is True and catalog.get("activeReleaseId") == RELEASE,
            "isolated commercial catalog")
    paid_paths = (CONTENT, f"{CONTENT}/lessons/core-01", f"{API}/me/plan", PROGRESS,
                  ATTEMPT_DRAFT, LAB, DRAFT, PROJECT)
    gate(guest, 401, paid_paths)
    expect(guest.request("HEAD", PROJECT)[0], 401, "guest HEAD")
    print("PASSED: commercial default denies anonymous content, learning, lab and ZIP", flush=True)

    buyer, name = register("buyer")
    other, other_name = register("other")
    staff, staff_name = register("staff")
    expect(buyer.request("GET", ACCESS)[0], 200, "query access")
    require(buyer.request("GET", ACCESS)[1] == {"required": True, "active": False}, "unpaid by default")
    gate(buyer, 403, paid_paths)
    expect(buyer.request("POST", PLAN, {"releaseId": RELEASE, "goalId": "python"})[0], 403, "unpaid preview")
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
    for path in (CONTENT, f"{CONTENT}/lessons/core-01", PROGRESS, LAB):
        expect(buyer.request("GET", path)[0], 200, f"entitled {path}")
    request = urllib.request.Request(ORIGIN + PROJECT)
    with buyer.opener.open(request, timeout=15) as response:
        require(response.read(4) == b"PK\x03\x04", "real project ZIP")
        require("no-store" in response.headers.get("Cache-Control", ""), "ZIP has no-store")
    gate(other, 403, [CONTENT, PROJECT])
    status, plan, _ = buyer.request("POST", PLAN, {"releaseId": RELEASE, "goalId": "python"})
    expect(status, 200, "entitled plan")
    require(len(plan["steps"]) == 24, "complete Python plan")
    status, _, _ = buyer.request("PUT", DRAFT, {"code": "print(6)", "expectedVersion": 0})
    expect(status, 200, "entitled lab draft")
    print("PASSED: admin grant and repeat, database state, authorized plan, draft, ZIP and CSRF", flush=True)

    if lab_budget:
        status, catalog, _ = buyer.request("GET", LAB)
        expect(status, 200, "lab catalog")
        require(catalog.get("available") is True, "isolated runner enabled")
        submission = {"releaseId": RELEASE, "lessonId": "py-02", "exerciseId": "py-02-lab",
                      "mode": "run", "code": "print(int(input()) * 6)", "input": "3\n",
                      "idempotencyKey": secrets.token_urlsafe(20)}
        trial = finish(buyer, send_run(buyer, submission), real_runner=True)
        require(trial["status"] == "completed" and trial["stdout"].strip() == "18", "execution returned 18")
        replay = send_run(buyer, submission)
        require(replay.get("id") == trial.get("id"), "idempotent submission")
        submission.pop("input")
        submission.update(mode="assess", idempotencyKey=secrets.token_urlsafe(20))
        assess = finish(buyer, send_run(buyer, submission), real_runner=True)
        require(assess["status"] == "completed" and assess["verdict"] == "passed", "assessment completed")
        submission.update(mode="run", idempotencyKey=secrets.token_urlsafe(20))
        status, error, _ = buyer.request("POST", f"{API}/lab/runs", submission)
        expect(status, 429, "budget reached")
        require(error.get("code") == "lab_daily_limit", "exhausted budget code")
        print("PASSED: configured runner execution and assessment, replay and daily execution cost limit", flush=True)
    else:
        print("SKIPPED: real runner budget test (requires an empty daily test budget of 4)", flush=True)

    status, access, _ = staff.request("POST", f"{ADMIN}/revoke", {"userName": name})
    expect(status, 200, "admin revoke")
    require(access.get("active") is False and buyer.request("GET", ACCESS)[1].get("active") is False,
            "revoke reflected in the existing session")
    gate(buyer, 403, paid_paths)
    expect(buyer.request("PUT", DRAFT, {"code": "print(9)", "expectedVersion": 1})[0], 403, "revoked writes")
    expect(buyer.request("HEAD", PROJECT)[0], 403, "revoked HEAD")
    expect(buyer.request("GET", f"{API}/auth/me")[0], 200, "account stays signed in")
    print("PASSED: revocation blocks same-session requests and downloads immediately", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--lab-budget", action="store_true")
    arguments = parser.parse_args()
    acceptance(arguments.assembly.resolve(strict=True), arguments.lab_budget)
