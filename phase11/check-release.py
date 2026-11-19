"""Verify Phase 11 publication and access on a disposable PostgreSQL cluster."""

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
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORKSPACE / "phase2/scripts"))
from http_integration import Client, expect, require


OLD, NEW = "phase10-ar-v1", "phase11-ar-v1"
BUNDLE = ROOT / "dist/curriculum.json"
PROJECTS = WORKSPACE / "phase2/apps/web/public/projects"
STARTERS = ("web", "react", "typescript", "backend", "algorithms", "oop", "problem-solving")


def free_port():
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        return endpoint.getsockname()[1]


def lesson_range(prefix, count):
    return [f"{prefix}-{number:02}" for number in range(1, count + 1)]


def request_after_rate_limit(send):
    status, body, headers = send()
    if status != 429:
        return status, body, headers
    retry_after = headers.get("Retry-After", "")
    require(retry_after.isdecimal() and 0 < int(retry_after) <= 60, "Expected a bounded Retry-After")
    print(f"Waiting {retry_after}s for the isolated API's request limit", flush=True)
    time.sleep(int(retry_after))
    return send()


def call(client, method, path, body=None, status=200):
    actual, result, _ = request_after_rate_limit(lambda: client.request(method, "/api/v1" + path, body))
    expect(actual, status, f"{method} {path}")
    return result


def register(origin, username):
    client = Client(origin)
    client.refresh_csrf()
    call(client, "POST", "/auth/register", {
        "userName": username,
        "displayName": "حساب اختبار المحتوى",
        "password": secrets.token_urlsafe(24),
    }, status=201)
    client.refresh_csrf()
    return client


def check_private_fields(content, label):
    serialized = json.dumps(content)
    for field in ("acceptedAnswers", "codeLab", "solution", "hiddenTests"):
        require(f'"{field}"' not in serialized, f"{label}: exposed {field}")
    for lesson in content.get("sample", {}).get("lessons", [content]):
        for exercise in lesson["exercises"]:
            require("explanation" not in exercise, f"{label}: exposed grading explanation")


def check_zip(client, starter, status):
    name = f"{starter}-starter-v1.zip"
    path = f"/projects/{name}"

    def download():
        try:
            response = client.opener.open(client.base + path, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read() if response.status == 200 else b"", response.headers

    actual, body, headers = request_after_rate_limit(download)
    expect(actual, status, f"GET {path}")
    if status == 200:
        require(headers.get("Cache-Control") == "no-store", f"{name}: download is private")
        require(hashlib.sha256(body).digest() == hashlib.sha256((PROJECTS / name).read_bytes()).digest(),
                f"{name}: download matches the reviewed ZIP")


def check_download_scope(client, content, starters, label):
    downloads = {project["download"] for project in content["sample"]["projects"] if "download" in project}
    require(downloads == {f"/projects/{starter}-starter-v1.zip" for starter in starters},
            f"{label}: visible download links match the granted scope")
    for starter in STARTERS:
        check_zip(client, starter, 200 if starter in starters else 403)


def check_journey(origin, command, publish, sql):
    admin_name = "phase11_review_admin"
    learner_name = "phase11_review_learner"
    prior_name = "phase11_review_prior"
    admin = register(origin, admin_name)
    learner = register(origin, learner_name)
    prior_learner = register(origin, prior_name)
    command("--promote-admin", admin_name)
    admin.refresh_csrf()
    guest = Client(origin)

    def access(action, username=learner_name, **scope):
        call(admin, "POST", "/admin/access/" + action, {"userName": username, **scope})

    def release_snapshot(release):
        return sql(f"""
            SELECT jsonb_build_object('release', to_jsonb(r), 'audit_count',
                (SELECT count(*) FROM public.audit a WHERE a.resource_id = r.id::text))
            FROM public.content_releases r WHERE r.release_id = '{release}';
        """)

    require(call(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 10 starts active")
    access("grant", username=prior_name, goalId="javascript-projects")
    prior = call(prior_learner, "POST", "/learning-plans",
                 {"releaseId": OLD, "goalId": "javascript-projects"}, status=201)
    old_content = call(prior_learner, "GET", "/content/" + OLD)
    old_snapshot = release_snapshot(OLD)
    require(old_snapshot, "Phase 10 exists")
    publish(BUNDLE)
    new_snapshot = release_snapshot(NEW)
    require(new_snapshot, "Phase 11 exists after publication")
    audit_count = sql("SELECT count(*) FROM public.audit;")
    publish(BUNDLE)
    require(release_snapshot(NEW) == new_snapshot, "repeat publication preserves the Phase 11 row")
    require(sql("SELECT count(*) FROM public.audit;") == audit_count, "repeat publication writes no audit event")
    require(release_snapshot(OLD) == old_snapshot, "Phase 10 row and audit count are unchanged")
    sql(f"""
        DO $$
        BEGIN
            UPDATE public.content_releases SET bundle = '{{}}'::jsonb WHERE release_id = '{OLD}';
            RAISE EXCEPTION 'Expected immutable Phase 10 bundle';
        EXCEPTION WHEN raise_exception THEN
            IF SQLERRM <> 'Content releases are immutable' THEN RAISE; END IF;
        END
        $$;
    """)
    require(call(prior_learner, "GET", "/me/plan") == prior, "published upgrade preserves the saved Phase 10 plan")
    require(call(prior_learner, "GET", "/content/" + OLD) == old_content,
            "Phase 10 remains published with identical content")
    print("PASSED: Phase 11 repeat publication, Phase 10 bundle immutability and saved plan", flush=True)

    core = lesson_range("core", 12)
    algorithms = core + lesson_range("alg", 8)
    oop = core + lesson_range("py", 12) + lesson_range("pyproj", 3) + lesson_range("oop", 6)
    problem_solving = algorithms + lesson_range("solve", 6)
    routes = (
        ("algorithms", algorithms, {"algorithms"}),
        ("oop", oop, {"oop"}),
        ("problem-solving", problem_solving, {"algorithms", "problem-solving"}),
    )
    catalog = call(guest, "GET", "/catalog")
    goals = {goal["id"] for goal in catalog["goals"]}
    require(catalog["activeReleaseId"] == NEW and len(goals) == 18 and all(goal in goals for goal, *_ in routes),
            "public catalog exposes all eighteen goals including the three Phase 11 additions")
    call(guest, "GET", "/content/" + NEW, status=401)
    call(learner, "GET", "/content/" + NEW, status=403)
    for starter in STARTERS:
        check_zip(guest, starter, 401)
        check_zip(learner, starter, 403)

    all_lessons = call(admin, "GET", "/content/" + NEW)
    lessons = all_lessons["sample"]["lessons"]
    require(len(lessons) == 110, "Admin sees all 110 lessons")
    require(sum(len(lesson["exercises"]) for lesson in lessons) == 304, "Admin sees all 304 exercises")
    require(int(sql(f"""
        SELECT jsonb_array_length(bundle->'codeLab') FROM public.content_releases WHERE release_id = '{NEW}';
    """)) == 46, "published bundle stores all 46 lab definitions")
    check_private_fields(all_lessons, "complete content")
    print("PASSED: 110 lessons, 304 graded exercises, 18 goals and 46 published labs", flush=True)

    bundle = json.loads(BUNDLE.read_bytes())
    new_labs = {}
    for lab in bundle["codeLab"]:
        if lab["lessonId"].startswith(("alg-", "oop-", "solve-")):
            new_labs.setdefault(lab["lessonId"], set()).add((lab["id"], lab["language"]))
    require(sum(map(len, new_labs.values())) == 10, "Phase 11 has ten new lab definitions")

    prices = {}
    for price, (goal, expected, starters) in enumerate(routes, 1):
        capstone = expected[-1]
        prices[goal] = (price, "EGP")
        call(admin, "PUT", "/admin/access/offers/" + goal, {"price": price, "currency": "EGP"})
        access("grant", goalId=goal)
        request = {"releaseId": NEW, "goalId": goal}
        preview = call(learner, "POST", "/plan-previews", request)
        require([step["lessonId"] for step in preview["steps"]] == expected and not preview["uncoveredSkillIds"],
                f"{goal}: exact {len(expected)}-lesson new learner prerequisite order")
        content = call(learner, "GET", "/content/" + NEW)
        require({lesson["id"] for lesson in content["sample"]["lessons"]} == set(expected),
                f"{goal}: purchased lessons and their prerequisites")
        require([item["id"] for item in content["graph"]["goals"]] == [goal], f"{goal}: isolated goal scope")
        check_private_fields(content, f"{goal} scoped content")
        check_private_fields(call(learner, "GET", f"/content/{NEW}/lessons/{capstone}"), capstone)
        check_download_scope(learner, content, starters, goal)
        for lesson_id, expected_labs in new_labs.items():
            endpoint = f"/lab/exercises/{NEW}/{lesson_id}"
            if lesson_id in expected:
                result = call(learner, "GET", endpoint)
                require({(lab["id"], lab["language"]) for lab in result["exercises"]} == expected_labs,
                        f"{goal}: {lesson_id} exposes the expected public lab metadata")
                check_private_fields(result, f"{lesson_id} lab metadata")
            else:
                call(learner, "GET", endpoint, status=403)
        access("revoke", goalId=goal)
        call(learner, "GET", f"/content/{NEW}/lessons/{capstone}", status=403)
        call(learner, "POST", "/plan-previews", request, status=403)
        for starter in sorted(starters):
            check_zip(learner, starter, 403)
        print(f"PASSED: {goal} path with {len(expected)} lessons, lab scope and ZIP revocation", flush=True)

    for allowed, expected, _ in routes:
        other, capstone = expected[-2:]
        access("grant", lessonId=capstone)
        content = call(learner, "GET", "/content/" + NEW)
        require([lesson["id"] for lesson in content["sample"]["lessons"]] == [capstone],
                f"{capstone}: single-lesson grant")
        check_private_fields(content, f"{capstone} scoped content")
        call(learner, "GET", f"/content/{NEW}/lessons/{other}", status=403)
        call(learner, "POST", "/plan-previews", {"releaseId": NEW, "goalId": allowed}, status=403)
        check_download_scope(learner, content, {allowed}, capstone)
        lesson = next(item for item in bundle["sample"]["lessons"] if item["id"] == capstone)
        exercise = lesson["exercises"][0]
        attempt = {"releaseId": NEW, "lessonId": capstone, "exerciseId": exercise["id"],
                   "answer": exercise["acceptedAnswers"][0], "hintsUsed": 0, "idempotencyKey": secrets.token_hex(12)}
        wrong = call(learner, "POST", "/practice/attempts",
                     {**attempt, "answer": "wrong_" + secrets.token_hex(12), "idempotencyKey": secrets.token_hex(12)})
        require(not wrong["correct"], f"{capstone}: incorrect answer is graded as incorrect")
        graded = call(learner, "POST", "/practice/attempts", attempt)
        replay = call(learner, "POST", "/practice/attempts", attempt)
        require(graded["correct"] and replay["id"] == graded["id"] and replay["alreadyRecorded"],
                f"{capstone}: grading and replay")
        access("revoke", lessonId=capstone)
        call(learner, "GET", f"/content/{NEW}/lessons/{capstone}", status=403)
        call(learner, "POST", "/practice/attempts", attempt, status=403)
        check_zip(learner, allowed, 403)
        print(f"PASSED: {capstone} single-lesson scope, grading and ZIP revocation", flush=True)

    def catalog_prices():
        return {offer["goalId"]: (offer["price"], offer["currency"])
                for offer in call(guest, "GET", "/catalog")["offers"]}

    require(catalog_prices() == prices, "the three goals expose separate prices")
    prices["oop"] = (25, "EGP")
    call(admin, "PUT", "/admin/access/offers/oop", {"price": 25, "currency": "EGP"})
    require(catalog_prices() == prices, "updating the OOP price leaves the other prices unchanged")
    print("PASSED: independent public prices and learner answer redaction", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--postgres-bin", required=True, type=Path, help="PostgreSQL binaries at an ASCII Windows path")
    args = parser.parse_args()
    assembly = args.assembly.resolve(strict=True)
    # Keep the Windows ASCII junction path for PostgreSQL's native utilities.
    pg = args.postgres_bin.absolute()
    for name in ("initdb.exe", "postgres.exe", "pg_isready.exe", "psql.exe", "pg_ctl.exe"):
        require((pg / name).is_file(), f"Missing PostgreSQL binary {name}")
    previous_bundles = [
        WORKSPACE / phase / "dist/curriculum.json"
        for phase in ("phase4", "phase7", "phase8", "phase9", "phase10")
    ]
    for path in (*previous_bundles, BUNDLE):
        require(path.is_file(), f"Missing curriculum bundle {path}")
    for starter in STARTERS:
        require((PROJECTS / f"{starter}-starter-v1.zip").is_file(), f"Missing {starter} starter ZIP")
    env = {key: value for key, value in os.environ.items() if not key.lower().startswith(
        ("pg", "masar_", "aspnetcore_", "dotnet_environment", "connectionstrings__", "kestrel__"))
        and key.lower() not in {"urls", "http_ports", "https_ports"}}
    owner_password, app_password = secrets.token_hex(24), secrets.token_hex(24)

    def redact(diagnostics):
        return diagnostics.replace(owner_password, "[redacted]").replace(app_password, "[redacted]")

    def run(command, **options):
        result = subprocess.run([str(argument) for argument in command], capture_output=True, timeout=45, **options)
        if result.returncode:
            diagnostics = redact((result.stdout + result.stderr).decode("utf-8", "replace"))
            raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}): {diagnostics}")
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="masar-phase11-http-") as directory:
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
        database_log = scratch / "postgres.log"
        with database_log.open("wb") as log:
            database = subprocess.Popen([pg / "postgres.exe", "-D", data, "-h", "127.0.0.1", "-p", str(db_port)],
                                        cwd=scratch, env=env, stdout=log, stderr=log)
        try:
            for _ in range(80):
                if database.poll() is not None:
                    diagnostics = redact(database_log.read_text(encoding="utf-8", errors="replace"))
                    raise RuntimeError(f"The disposable database exited ({database.returncode}): {diagnostics}")
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
                return run(["dotnet", assembly, *arguments], cwd=scratch, env=settings)

            def publish(path):
                command("--publish-reviewed-curriculum", path, hashlib.sha256(path.read_bytes()).hexdigest())

            def sql(statement):
                return run([pg / "psql.exe", "-X", "-w", "-h", "127.0.0.1", "-p", db_port,
                            "-U", "qa_owner", "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1"],
                           input=statement.encode("ascii"), env=dict(env, PGPASSWORD=owner_password))

            command("--migrate")
            sql(f"""
                CREATE ROLE qa_app LOGIN PASSWORD '{app_password}';
                GRANT USAGE ON SCHEMA public TO qa_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO qa_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO qa_app;
            """)
            initial = scratch / "initial.json"
            initial.write_text(json.dumps({name: json.loads((WORKSPACE / f"phase1/content/{name}.json").read_text(
                encoding="utf-8-sig")) for name in ("sample", "graph")}), encoding="utf-8")
            command("--import-bundle", initial, "--publish-initial")
            for path in previous_bundles:
                publish(path)
            project_root = scratch / "wwwroot/projects"
            project_root.mkdir(parents=True)
            for starter in STARTERS:
                name = f"{starter}-starter-v1.zip"
                shutil.copyfile(PROJECTS / name, project_root / name)
            api_log = scratch / "api.log"
            with api_log.open("wb") as log:
                process = subprocess.Popen(["dotnet", str(assembly)], cwd=scratch,
                                           env={key: value for key, value in settings.items() if key != "ConnectionStrings__Migration"},
                                           stdout=log, stderr=log)
            try:
                for _ in range(80):
                    if process.poll() is not None:
                        diagnostics = redact(api_log.read_text(encoding="utf-8", errors="replace"))
                        raise RuntimeError(f"The isolated API exited ({process.returncode}): {diagnostics}")
                    try:
                        if Client(origin).request("GET", "/api/v1/health")[0] == 200:
                            break
                    except OSError:
                        pass
                    time.sleep(.25)
                else:
                    raise RuntimeError("The isolated API did not become healthy")
                check_journey(origin, command, publish, sql)
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
