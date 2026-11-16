"""HTTP/PostgreSQL integration using a fixed-response fixture or the configured isolated runner."""

import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from threading import Thread
import time

PHASE_TWO = Path(__file__).resolve().parent.parent / "phase2"
sys.path.insert(0, str(PHASE_TWO / "scripts"))
from http_integration import Client, expect, require

RELEASE = "phase1-ar-v1"
LESSON = "what-is-a-program"
EXERCISE = "python-greeting"
CODE = "print('أهلًا ' + input())"
JS_CODE = "const price = Number(require('node:fs').readFileSync(0, 'utf8').trim());\nconsole.log((price + 3) * 2);"
DRAFT = f"/api/v1/lab/drafts/{RELEASE}/{EXERCISE}"
CATALOG = f"/api/v1/lab/exercises/{RELEASE}/{LESSON}"
EVIDENCE = f"/api/v1/lab/evidence?releaseId={RELEASE}"
RUNS = "/api/v1/lab/runs"
JAVASCRIPT = dict(exerciseId="javascript-price", lessonId="step-by-step")


def configured_runner():
    config = {name: os.environ.get(name, "").strip() for name in
              ("MASAR_CODE_LAB_RUNNER_URL", "MASAR_CODE_LAB_RUNNER_TOKEN")}
    if not all(config.values()):
        raise SystemExit("Real runner acceptance requires the runner URL and token in the process environment.")
    return config | {"MASAR_CODE_LAB_ENABLED": "true"}


@contextlib.contextmanager
def runner_fixture():
    token = secrets.token_urlsafe(32)

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/v1/execute" or self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(403)
                return
            length = self.headers.get("Content-Length", "")
            if self.headers.get("Transfer-Encoding") or not length.isdecimal():
                self.send_error(400)
                return
            size = int(length)
            if size > 131072:
                self.send_error(413)
                return
            request = json.loads(self.rfile.read(size))
            status, stdout, stderr = "completed", "", ""
            if request["code"] == CODE and request["language"] == "python":
                stdout = "أهلًا " + request["stdin"].rstrip("\n") + "\n"
            elif request["code"] == JS_CODE and request["language"] == "javascript":
                stdout = f"{(int(request['stdin']) + 3) * 2}\n"
            elif request["code"] == "print('أهلًا ليلى')":
                stdout = "أهلًا ليلى\n"
            elif request["code"] == "# fixture: unavailable":
                status = "infrastructure_error"
            elif request["code"] == "# fixture: time limit":
                status = "timed_out"
            else:
                status, stderr = "code_error", "Fixture has no result for this snippet."
            payload = json.dumps(dict(status=status, stdout=stdout, stderr=stderr)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), Fixture) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield {
                "MASAR_CODE_LAB_ENABLED": "true",
                "MASAR_CODE_LAB_RUNNER_URL": f"http://127.0.0.1:{server.server_port}",
                "MASAR_CODE_LAB_RUNNER_TOKEN": token,
            }
        finally:
            server.shutdown()
            thread.join()


@contextlib.contextmanager
def test_api(api, origin, runner_config=None, content_root=None):
    runtime = os.environ.copy()
    connection = os.environ.get("ConnectionStrings__Masar", "")
    parts = [item.partition("=") for item in connection.strip(";").split(";")]
    fields = {key.strip().lower(): value for key, separator, value in parts if separator}
    allowed = {"host", "port", "database", "username", "password", "timeout", "command timeout", "include error detail"}
    if (len(fields) != len(parts) or not fields.keys() <= allowed or
            fields.get("host") != "127.0.0.1" or fields.get("database") != "masar_phase2_tests"):
        raise SystemExit("This suite requires the dedicated test database.")
    for name in ("MASAR_CODE_LAB_ENABLED", "MASAR_CODE_LAB_RUNNER_URL",
                 "MASAR_CODE_LAB_RUNNER_TOKEN", "ConnectionStrings__Migration"):
        runtime.pop(name.upper() if os.name == "nt" else name, None)
    runtime.update(ASPNETCORE_URLS=origin)
    runtime.update(runner_config or {})
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", int(origin.rsplit(":", 1)[1])))
    process = subprocess.Popen(["dotnet", str(api)], cwd=content_root or PHASE_TWO / "src" / "Masar.Api",
                               env=runtime, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            require(process.poll() is None, "Owned test API exited during startup.")
            try:
                if Client(origin).request("GET", "/api/v1/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            raise AssertionError("Owned test API did not become healthy.")
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def register(base):
    client = Client(base)
    client.refresh_csrf()
    status, _, _ = client.request("POST", "/api/v1/auth/register", {
        "userName": f"lab_qa_{secrets.token_hex(6)}",
        "displayName": "متعلم اختبار",
        "password": secrets.token_urlsafe(26),
    })
    expect(status, 201, "test registration")
    client.refresh_csrf()
    return client


def submission(mode, code=CODE, **fields):
    return dict(releaseId=RELEASE, lessonId=LESSON, exerciseId=EXERCISE, mode=mode,
                code=code, idempotencyKey=secrets.token_urlsafe(20)) | fields


def send_run(client, body):
    status, result, _ = client.request("POST", RUNS, body)
    expect(status, (200, 202), "submit")
    return result


def finish(client, result, real_runner=False):
    deadline = time.monotonic() + (125 if real_runner else 12)
    while result["status"] == "running" and time.monotonic() < deadline:
        time.sleep(1.5 if real_runner else 0.25)
        status, result, _ = client.request("GET", f"{RUNS}/{result['id']}")
        expect(status, 200, "poll")
    require(result["status"] != "running", "run reached a terminal state")
    return result


def preview(client):
    status, plan, _ = client.request("POST", "/api/v1/plan-previews", {
        "releaseId": RELEASE, "goalId": "explore",
    })
    expect(status, 200, "plan preview")
    return plan


def run_suite(api, base, real_runner=False):
    runner = contextlib.nullcontext(configured_runner()) if real_runner else runner_fixture()
    print("Runner mode: " + ("configured isolated broker" if real_runner else "fixed-response fixture"), flush=True)
    guest = Client(base)
    with test_api(api, base):
        status, catalog, _ = guest.request("GET", CATALOG)
        expect(status, 200, "disabled catalog")
        require(catalog["available"] is False and len(catalog["exercises"]) == 1, "disabled catalog lists exercise")
        require("hiddenTests" not in json.dumps(catalog) and "Maya" not in json.dumps(catalog), "private cases stay on server")
        expect(guest.request("GET", DRAFT)[0], 401, "guest draft")
        learner, other = register(base), register(base)
        expect(learner.request("POST", RUNS, submission("assess"))[0], 503, "disabled submission")
        expect(learner.request("PUT", DRAFT, dict(code=CODE, expectedVersion=0), csrf=False)[0], 400, "missing CSRF")
        expect(learner.request("PUT", DRAFT, dict(code=CODE, expectedVersion=0))[0], 200, "save disabled draft")
        expect(learner.request("PUT", DRAFT, dict(code=CODE, expectedVersion=0))[0], 409, "stale draft")
        expect(other.request("GET", DRAFT)[0], 404, "private draft")
        print("PASSED: disabled execution, public catalog, CSRF, private versioned drafts", flush=True)

    with runner as config, test_api(api, base, config):
        def complete(body):
            return finish(learner, send_run(learner, body), real_runner)

        status, draft, _ = learner.request("GET", DRAFT)
        expect(status, 200, "draft after process restart")
        require(draft == {"code": CODE, "version": 1}, "persistent exact draft")
        require(guest.request("GET", CATALOG)[1]["available"] is True, "enabled catalog")
        baseline = preview(learner)
        free = complete(submission("run", input="اختبار\n"))
        require(free["status"] == "completed" and free["stdout"] == "أهلًا اختبار\n" and
                free["verdict"] == "not_evaluated", "free run shows output without grading")
        require(learner.request("GET", EVIDENCE)[1] == [], "free run earns no evidence")
        expect(other.request("GET", f"{RUNS}/{free['id']}")[0], 404, "private run")
        print("PASSED: draft and session survive restart, free run, no evidence, private run", flush=True)

        wrong = complete(submission("assess", "print('أهلًا ليلى')"))
        require(wrong["verdict"] == "needs_work" and wrong["passedCases"] == 1 and wrong["totalCases"] == 3
                and not wrong["stdout"] and not wrong["stderr"], "sample-only answer fails private tests")
        if real_runner:
            failures = [
                ("code_error", submission("assess", "print(1 / 0)")),
                ("timed_out", submission("assess", "import time\ntime.sleep(10)")),
                ("output_limit", submission("run", "console.log('x'.repeat(20000))", **JAVASCRIPT)),
            ]
        else:
            failures = [
                ("infrastructure_error", submission("assess", "# fixture: unavailable")),
                ("timed_out", submission("assess", "# fixture: time limit")),
            ]
        for expected, body in failures:
            failed = complete(body)
            expect(failed["status"], expected, "terminal runner status")
            require(failed["verdict"] == "not_evaluated" and "passedCases" not in failed and "totalCases" not in failed,
                    "runner limits and failures produce no grade")
            require(len(failed["stdout"].encode()) + len(failed["stderr"].encode()) <= 16 * 1024,
                    "runner output stays within the response limit")
            if body["mode"] == "assess":
                require(not failed["stdout"] and not failed["stderr"], "failed assessment keeps case output private")
        require(learner.request("GET", EVIDENCE)[1] == [], "failed evaluations award nothing")
        print("PASSED: curated cases, hidden output, " + ", ".join(status for status, _ in failures), flush=True)

        body = submission("assess")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send_run(learner.clone(), body), range(2)))
        require(results[0]["id"] == results[1]["id"] and any(r["alreadyRecorded"] for r in results),
                "simultaneous same key shares one submission")
        result = finish(learner, results[0], real_runner)
        require(result["verdict"] == "passed" and result["passedCases"] == 3, "all cases pass")
        expect(learner.request("POST", RUNS, body | {"code": "print(42)"})[0], 409, "changed payload with same key")
        second = complete(submission("assess"))
        require(second["verdict"] == "passed" and second["id"] != result["id"], "a new attempt can pass again")
        evidence = learner.request("GET", EVIDENCE)[1]
        require(len(evidence) == 1 and evidence[0]["skillId"] == "concept.input-output", "only one evidence entry")
        require(other.request("GET", EVIDENCE)[1] == [], "private evidence")
        changed = preview(learner)
        require("concept.input-output" in baseline["missingSkillIds"] and
                "concept.input-output" not in changed["missingSkillIds"], "new plan uses the evidence")
        print("PASSED: concurrent idempotency, duplicate evidence protection and updated plan", flush=True)
        javascript_trial = complete(submission("run", JS_CODE, input="7\n", **JAVASCRIPT))
        require(javascript_trial["status"] == "completed" and javascript_trial["stdout"] == "20\n" and
                javascript_trial["verdict"] == "not_evaluated", "JavaScript trial returns the custom-input output")
        require(learner.request("GET", EVIDENCE)[1] == evidence, "JavaScript trial earns no evidence")
        javascript = submission("assess", JS_CODE, **JAVASCRIPT)
        result = complete(javascript)
        require(result["verdict"] == "passed" and result["passedCases"] == 3, "JavaScript case routing and grading")
        status, earned, _ = learner.request("GET", EVIDENCE)
        expect(status, 200, "load final evidence")
        require({(item["skillId"], item["exerciseId"]) for item in earned} ==
                {("concept.input-output", EXERCISE), ("concept.sequence", JAVASCRIPT["exerciseId"])} and len(earned) == 2,
                "one evidence entry per solved exercise")
        print("PASSED: JavaScript trial and assessment, coding evidence for both exercises", flush=True)

    if real_runner:
        with test_api(api, base, config):
            replay = send_run(learner, javascript)
            require(replay["id"] == result["id"] and replay["verdict"] == "passed" and replay["alreadyRecorded"],
                    "a completed assessment is replayable after API restart")
            require(learner.request("GET", EVIDENCE)[1] == earned, "evidence persists after API restart")
            print("PASSED: real assessment result and evidence persist after API restart", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api", type=Path)
    parser.add_argument("--real-runner", action="store_true", help="execute through the configured isolated broker")
    args = parser.parse_args()
    run_suite(args.api.resolve(strict=True), "http://127.0.0.1:5182", args.real_runner)
