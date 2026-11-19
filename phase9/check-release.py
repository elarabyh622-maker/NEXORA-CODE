"""Check Phase 9 publication and paid curriculum scopes on a disposable PostgreSQL cluster."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
sys.path.insert(0, str(WORKSPACE / "phase2/scripts"))
from http_integration import Client, expect, require

OLD, NEW = "phase8-ar-v1", "phase9-ar-v1"


def free_port():
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        return endpoint.getsockname()[1]


def lesson_range(prefix, count):
    return [f"{prefix}-{number:02}" for number in range(1, count + 1)]


def call(client, method, path, body=None, status=200):
    actual, result, _ = client.request(method, "/api/v1" + path, body)
    expect(actual, status, path)
    return result


def register(origin, username):
    client = Client(origin)
    client.refresh_csrf()
    call(client, "POST", "/auth/register", {"userName": username, "displayName": "حساب اختبار المحتوى",
                                            "password": secrets.token_urlsafe(24)}, status=201)
    client.refresh_csrf()
    return client


def check_journey(origin, command, publish):
    admin = register(origin, "phase9_review_admin")
    learner = register(origin, "phase9_review_learner")
    command("--promote-admin", "phase9_review_admin")
    admin.refresh_csrf()
    guest = Client(origin)

    def access(action, **scope):
        call(admin, "POST", "/admin/access/" + action, {"userName": "phase9_review_learner", **scope})

    access("grant", goalId="python")
    prior = call(learner, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "python"}, status=201)
    old_content = call(learner, "GET", "/content/" + OLD)
    publish(ROOT / "dist/curriculum.json")
    publish(ROOT / "dist/curriculum.json")
    require(call(learner, "GET", "/me/plan") == prior, "published upgrade preserves the saved plan")
    require(call(learner, "GET", "/content/" + OLD) == old_content, "Phase 8 remains immutable and published")
    access("revoke", goalId="python")

    bundle = json.loads((ROOT / "dist/curriculum.json").read_bytes())
    catalog = call(guest, "GET", "/catalog")
    require(catalog["activeReleaseId"] == NEW and len(catalog["goals"]) == 11,
            "public catalog exposes the eleven Phase 9 goals")
    call(guest, "GET", "/content/" + NEW, status=401)
    call(learner, "GET", "/content/" + NEW, status=403)

    python = lesson_range("core", 12) + lesson_range("py", 12) + lesson_range("pyproj", 3)
    sql = lesson_range("sql", 6) + lesson_range("sql-write", 4)
    backend = python + lesson_range("backend", 3) + sql + lesson_range("backend", 7)[3:]
    fullstack = backend + lesson_range("web", 12) + lesson_range("web-data", 5) + lesson_range("fullstack", 2)
    # This learner completes each capstone below. Later previews reuse the resulting skill evidence.
    new_learner_web = lesson_range("core", 12) + lesson_range("web", 12) + lesson_range("web-data", 5)
    routes = (("python-projects", python, python, "pyproj-03"), ("sql-write", sql, sql, "sql-write-04"),
              ("backend", backend, lesson_range("backend", 7), "backend-07"),
              ("fullstack", fullstack, new_learner_web + lesson_range("fullstack", 2), "fullstack-02"))
    by_id = {lesson["id"]: lesson for lesson in bundle["sample"]["lessons"]}
    for index, (goal, expected_lessons, remaining_lessons, capstone) in enumerate(routes, 1):
        call(admin, "PUT", "/admin/access/offers/" + goal, {"price": index, "currency": "EGP"})
        access("grant", goalId=goal)
        complete = call(admin, "POST", "/plan-previews", {"releaseId": NEW, "goalId": goal})
        require([step["lessonId"] for step in complete["steps"]] == expected_lessons,
                f"{goal}: exact new learner prerequisite order")
        preview = call(learner, "POST", "/plan-previews", {"releaseId": NEW, "goalId": goal})
        require([step["lessonId"] for step in preview["steps"]] == remaining_lessons,
                f"{goal}: reuse previously demonstrated skills")
        content = call(learner, "GET", "/content/" + NEW)
        require({lesson["id"] for lesson in content["sample"]["lessons"]} == set(expected_lessons),
                f"{goal}: purchased lessons and their prerequisites")
        serialized = json.dumps(content)
        require(not any('"' + key + '"' in serialized for key in ("acceptedAnswers", "codeLab", "solution", "hiddenTests")),
                "answers and hidden checks must be private")
        for exercise in by_id[capstone]["exercises"]:
            request = {"releaseId": NEW, "lessonId": capstone, "exerciseId": exercise["id"],
                       "answer": exercise["acceptedAnswers"][0], "hintsUsed": 0, "idempotencyKey": secrets.token_hex(12)}
            result = call(learner, "POST", "/practice/attempts", request)
            require(result["correct"], f"{capstone}: capstone grading")
            replay = call(learner, "POST", "/practice/attempts", request)
            require(replay["id"] == result["id"] and replay["alreadyRecorded"], "grading replay")
        status, _, _ = learner.request("HEAD", "/projects/backend-starter-v1.zip")
        expect(status, 200 if goal in {"backend", "fullstack"} else 403, "project download scope")
        if goal in {"backend", "fullstack"}:
            payload = learner.opener.open(origin + "/projects/backend-starter-v1.zip", timeout=10).read()
            expected = WORKSPACE / "phase2/apps/web/public/projects/backend-starter-v1.zip"
            require(hashlib.sha256(payload).digest() == hashlib.sha256(expected.read_bytes()).digest(),
                    "project download matches reviewed starter")
        if goal == "fullstack":
            expect(learner.request("HEAD", "/projects/web-starter-v1.zip")[0], 200, "web prerequisite download")
        access("revoke", goalId=goal)
        call(learner, "GET", f"/content/{NEW}/lessons/{capstone}", status=403)
        expect(learner.request("HEAD", "/projects/backend-starter-v1.zip")[0], 403, "revoked project download")

    access("grant", lessonId="backend-07")
    expect(learner.request("HEAD", "/projects/backend-starter-v1.zip")[0], 200, "single capstone download")
    call(learner, "GET", f"/content/{NEW}/lessons/backend-06", status=403)
    access("revoke", lessonId="backend-07")
    require(len(call(guest, "GET", "/catalog")["offers"]) == 4, "new goals support independent prices")
    require(len(call(admin, "GET", "/content/" + NEW)["sample"]["lessons"]) == 76, "Admin sees all lessons")
    print("PASSED: Phase 8 plan preservation, repeat publication, four exact new paths, paid scopes, grading and downloads")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--postgres-bin", required=True, type=Path, help="PostgreSQL binaries at an ASCII Windows path")
    args = parser.parse_args()
    assembly, pg = args.assembly.resolve(strict=True), args.postgres_bin.resolve(strict=True)
    # Keep the native ASCII junction path. Resolving it would reintroduce a non-ASCII path on this machine.
    pg = args.postgres_bin.absolute()
    require((pg / "initdb.exe").is_file(), "Expected Windows PostgreSQL binaries")
    env = {key: value for key, value in os.environ.items() if not key.lower().startswith(
        ("pg", "masar_", "aspnetcore_", "dotnet_environment", "connectionstrings__"))}
    owner_password, app_password = secrets.token_hex(24), secrets.token_hex(24)

    def run(command, **options):
        result = subprocess.run([str(argument) for argument in command], capture_output=True, timeout=45, **options)
        if result.returncode:
            diagnostics = (result.stdout + result.stderr).decode("utf-8", "replace")
            diagnostics = diagnostics.replace(owner_password, "[redacted]").replace(app_password, "[redacted]")
            raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}): {diagnostics}")
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="nexora-phase9-http-") as directory:
        scratch = Path(directory)
        data = scratch / "data"
        password_file = scratch / "bootstrap.txt"
        password_file.write_text(owner_password, encoding="ascii")
        try:
            run([pg / "initdb.exe", "-D", data, "-U", "qa_owner", "-A", "scram-sha-256", "--pwfile", password_file,
                 "--locale=C", "--encoding=UTF8"], env=env)
        finally:
            password_file.unlink()
        db_port, api_port = free_port(), free_port()
        while api_port == db_port:
            api_port = free_port()
        with (scratch / "postgres.log").open("wb") as log:
            database = subprocess.Popen([pg / "postgres.exe", "-D", data, "-h", "127.0.0.1", "-p", str(db_port)],
                                        cwd=scratch, env=env, stdout=log, stderr=log)
        try:
            for _ in range(80):
                require(database.poll() is None, "The disposable database exited")
                if subprocess.run([pg / "pg_isready.exe", "-q", "-h", "127.0.0.1", "-p", str(db_port)], env=env).returncode == 0:
                    break
                time.sleep(.25)
            else:
                raise RuntimeError("The disposable database did not become ready")
            origin = f"http://127.0.0.1:{api_port}"
            connection = f"Host=127.0.0.1;Port={db_port};Database=postgres;Timeout=5;"
            settings = dict(env, ASPNETCORE_ENVIRONMENT="Development", ASPNETCORE_URLS=origin,
                            MASAR_COMMERCIAL_ENABLED="true", MASAR_COMMERCIAL_SESSION_NAMESPACE="CommercialTest",
                            MASAR_CODE_LAB_ENABLED="false", MASAR_DATA_ROOT=str(scratch / "runtime"),
                            ConnectionStrings__Migration=connection + f"Username=qa_owner;Password={owner_password}",
                            ConnectionStrings__Masar=connection + f"Username=qa_app;Password={app_password}")

            def command(*arguments):
                return run(["dotnet", assembly, *arguments], cwd=assembly.parent, env=settings)

            def publish(path):
                command("--publish-reviewed-curriculum", path, hashlib.sha256(path.read_bytes()).hexdigest())

            command("--migrate")
            grants = f"CREATE ROLE qa_app LOGIN PASSWORD '{app_password}'; " + (
                "GRANT USAGE ON SCHEMA public TO qa_app; "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO qa_app; "
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO qa_app;")
            run([pg / "psql.exe", "-X", "-w", "-h", "127.0.0.1", "-p", db_port, "-U", "qa_owner", "-d", "postgres",
                 "-v", "ON_ERROR_STOP=1"], input=grants.encode("ascii"), env=dict(env, PGPASSWORD=owner_password))
            initial = scratch / "initial.json"
            initial.write_text(json.dumps({name: json.loads((WORKSPACE / f"phase1/content/{name}.json").read_text(
                encoding="utf-8-sig")) for name in ("sample", "graph")}), encoding="utf-8")
            command("--import-bundle", initial, "--publish-initial")
            for phase in ("phase4", "phase7", "phase8"):
                publish(WORKSPACE / phase / "dist/curriculum.json")
            shutil.copytree(WORKSPACE / "phase2/apps/web/public/projects", assembly.parent / "wwwroot/projects", dirs_exist_ok=True)
            with (scratch / "api.log").open("wb") as log:
                process = subprocess.Popen(["dotnet", str(assembly)], cwd=assembly.parent,
                                           env={key: value for key, value in settings.items() if key != "ConnectionStrings__Migration"},
                                           stdout=log, stderr=log)
            try:
                for _ in range(80):
                    require(process.poll() is None, "The isolated API exited. Check Windows DPAPI in this user context.")
                    try:
                        if Client(origin).request("GET", "/api/v1/health")[0] == 200:
                            break
                    except OSError:
                        pass
                    time.sleep(.25)
                else:
                    raise RuntimeError("The isolated API did not become healthy")
                check_journey(origin, command, publish)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=15)
        finally:
            if database.poll() is None:
                try:
                    run([pg / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop"], env=env)
                finally:
                    if database.poll() is None:
                        database.terminate()
                    database.wait(timeout=10)


if __name__ == "__main__":
    main()
