"""Check a Phase 4 to Phase 7 upgrade in the dedicated local PostgreSQL fixture."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "phase3"))
sys.path.insert(0, str(HERE.parent / "phase2" / "scripts"))
from http_integration import Client, expect, require
from test_code_lab_http import finish, register, send_run

ORIGIN = "http://127.0.0.1:5197"
API = "/api/v1"
OLD = "phase4-ar-v1"
NEW = "phase7-ar-v1"
GOAL = "data-analysis"


def check_connections():
    for name, user in (("Masar", "phase7_app"), ("Migration", "phase7_owner")):
        connection = os.environ.get(f"ConnectionStrings__{name}", "")
        fields = {key.lower(): value for key, _, value in (
            part.partition("=") for part in connection.split(";")
        )}
        require((fields.get("host"), fields.get("port"), fields.get("database"), fields.get("username")) ==
                ("127.0.0.1", "55437", "phase7_checks", user), "the isolated Phase 7 test database is required")


@contextlib.contextmanager
def test_server(assembly, real_runner):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 5197))
    env = {key: value for key, value in os.environ.items() if key.lower() != "connectionstrings__migration"}
    env.update(ASPNETCORE_URLS=ORIGIN, ASPNETCORE_ENVIRONMENT="Development",
               MASAR_COMMERCIAL_ENABLED="false", MASAR_PILOT_FUNNEL="false")
    if not real_runner:
        env["MASAR_CODE_LAB_ENABLED"] = "false"
    process = subprocess.Popen(["dotnet", str(assembly)], cwd=assembly.parent, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        guest = Client(ORIGIN)
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline and process.poll() is None:
            try:
                if guest.request("GET", f"{API}/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.4)
        else:
            raise RuntimeError("The isolated API did not become healthy.")
        yield guest
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)


def request(client, method, path, body=None, status=200):
    actual, payload, _ = client.request(method, API + path, body)
    expect(actual, status, path)
    return payload


def forbidden_fields(value):
    if isinstance(value, dict):
        return any(key in {"acceptedAnswers", "codeLab", "hiddenTests", "solution", "testCases"} or
                   forbidden_fields(item) for key, item in value.items())
    if isinstance(value, list):
        return any(forbidden_fields(item) for item in value)
    return False


def ids(prefix, length):
    return [f"{prefix}-{number:02}" for number in range(1, length + 1)]


def capstone_definition():
    source = json.loads((HERE / "content" / "data-project.json").read_text(encoding="utf-8-sig"))
    return next(item for item in source["labs"] if item["lessonId"] == "data-08")


def verify_capstone(learner, lab):
    result = finish(learner, send_run(learner, {
        "releaseId": NEW, "lessonId": "data-08", "exerciseId": lab["id"],
        "mode": "assess", "code": lab["solution"], "idempotencyKey": secrets.token_urlsafe(20),
    }), real_runner=True)
    require(result["status"] == "completed" and result["verdict"] == "passed",
            f"capstone assessment failed with {result['status']}/{result['verdict']}")
    evidence = request(learner, "GET", f"/lab/evidence?releaseId={NEW}")
    require(any(item["skillId"] == "data.project" and item["exerciseId"] == lab["id"] for item in evidence),
            "project evidence recorded")
    print("PASSED: capstone assessment on gVisor with PostgreSQL evidence", flush=True)


def verify(assembly, real_runner, browser_check):
    check_connections()
    bundle_path = HERE / "dist" / "curriculum.json"
    bundle = json.loads(bundle_path.read_bytes())
    sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    capstone = capstone_definition()
    quiz = next(lesson for lesson in bundle["sample"]["lessons"] if lesson["id"] == "data-01")["exercises"][0]
    with test_server(assembly, real_runner) as guest:
        require(request(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 4 must be initially active")
        before = request(guest, "GET", f"/content/{OLD}")
        learner = register(ORIGIN)
        plan = request(learner, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "python"}, status=201)
        command = ["dotnet", str(assembly), "--publish-reviewed-curriculum", str(bundle_path), sha]
        for _ in range(2):
            subprocess.run(command, cwd=assembly.parent, check=True, timeout=20)
        catalog = request(guest, "GET", "/catalog")
        require(catalog["activeReleaseId"] == NEW, "Phase 7 activation")
        require(request(guest, "GET", f"/content/{OLD}") == before, "original published content preserved")
        require(request(learner, "GET", "/me/plan") == plan, "saved Phase 4 revision remains pinned")
        print("PASSED: PostgreSQL activation, safe replay, original release and learner plan preserved", flush=True)

        guest.refresh_csrf()
        core = ids("core", 12)
        python = ids("py", 12)
        data = ids("data", 8)
        for goal, expected in (("explore", core), ("python", core + python), ("web", core + ids("web", 12)),
                               (GOAL, core + python + data)):
            preview = request(guest, "POST", "/plan-previews", {"releaseId": NEW, "goalId": goal})
            require([step["lessonId"] for step in preview["steps"]] == expected,
                    f"exact prerequisite order for {goal}")
        public = request(guest, "GET", f"/content/{NEW}")
        require(len(public["sample"]["lessons"]) == 44 and not forbidden_fields(public),
                "public release contains 44 lessons with answers and hidden cases removed")
        first = request(guest, "GET", f"/content/{NEW}/lessons/data-01")
        labs = request(guest, "GET", f"/lab/exercises/{NEW}/data-08")
        require(not forbidden_fields(first) and not forbidden_fields(labs), "exercise privacy")
        require(any(item["id"] == capstone["id"] for item in labs["exercises"]), "capstone lab listed")

        body = dict(releaseId=NEW, lessonId="data-01", exerciseId=quiz["id"], hintsUsed=0,
                    answer=quiz["acceptedAnswers"][0], idempotencyKey=secrets.token_urlsafe(20))
        graded = request(learner, "POST", "/practice/attempts", body)
        require(graded["correct"], "new exercise grading")
        replay = request(learner, "POST", "/practice/attempts", body)
        require(replay["id"] == graded["id"] and replay["alreadyRecorded"], "attempt replay")
        print("PASSED: four exact paths, public answer privacy and data exercise grading", flush=True)

        if browser_check:
            subprocess.run(["node", str(browser_check)], cwd=HERE.parent, check=True, timeout=75)
        if real_runner:
            require(labs["available"], "real runner is active in the isolated API")
            verify_capstone(learner, capstone)
        else:
            print("SKIPPED: end-to-end capstone assessment requires the actual gVisor broker", flush=True)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser()
    arguments.add_argument("assembly", type=Path)
    arguments.add_argument("--real-runner", action="store_true")
    arguments.add_argument("--browser-check", type=Path)
    arguments.add_argument("--capstone-only", action="store_true")
    options = arguments.parse_args()
    resolved = options.assembly.resolve(strict=True)
    if options.capstone_only:
        if not options.real_runner:
            arguments.error("--capstone-only requires --real-runner")
        check_connections()
        with test_server(resolved, True) as guest:
            require(request(guest, "GET", "/catalog")["activeReleaseId"] == NEW, "the test release must be active")
            require(request(guest, "GET", f"/lab/exercises/{NEW}/data-08")["available"], "real runner is required")
            verify_capstone(register(ORIGIN), capstone_definition())
    else:
        verify(resolved, options.real_runner, options.browser_check.resolve(strict=True) if options.browser_check else None)
