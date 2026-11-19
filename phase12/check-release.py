"""Verify the reviewed Phase 12 release on a disposable local PostgreSQL cluster."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
OLD, NEW = "phase11-ar-v1", "phase12-ar-v1"
GOAL, CAPSTONE = "applied-data", "applied-01"
STARTER = "applied-data"
ZIP_NAME = f"{STARTER}-starter-v1.zip"
DOWNLOAD = f"/projects/{ZIP_NAME}"
PROJECTS = WORKSPACE / "phase2/apps/web/public/projects"
PREVIOUS = [
    WORKSPACE / phase / "dist/curriculum.json"
    for phase in ("phase4", "phase7", "phase8", "phase9", "phase10", "phase11")
]

# Share the exercised HTTP assertions while keeping the Phase 11 check runnable as-is.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "phase11_check_release", WORKSPACE / "phase11/check-release.py"
)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
Client = checks.Client
call = checks.call
check_private_fields = checks.check_private_fields
check_zip = checks.check_zip
free_port = checks.free_port
lesson_range = checks.lesson_range
register = checks.register
require = checks.require


def release_snapshot(sql, release_id):
    return sql(f"""
        SELECT jsonb_build_object('release', to_jsonb(r), 'audit_count',
            (SELECT count(*) FROM public.audit a WHERE a.resource_id = r.id::text))
        FROM public.content_releases r WHERE r.release_id = '{release_id}';
    """)


def check_upgrade(guest, prior, access, publish, sql):
    require(call(guest, "GET", "/catalog")["activeReleaseId"] == OLD, "Phase 11 starts active")
    access("grant", "phase12_review_prior", goalId="oop")
    old_plan = call(prior, "POST", "/learning-plans", {"releaseId": OLD, "goalId": "oop"}, status=201)
    old_content = call(prior, "GET", f"/content/{OLD}")
    old_snapshot = release_snapshot(sql, OLD)
    require(old_snapshot and old_plan["releaseId"] == OLD, "Phase 11 plan and release exist")

    publish()
    new_snapshot = release_snapshot(sql, NEW)
    require(new_snapshot, "Phase 12 exists after publication")
    audit_count = sql("SELECT count(*) FROM public.audit;")
    publish()
    require(release_snapshot(sql, NEW) == new_snapshot, "Repeat publication preserves the Phase 12 row")
    require(sql("SELECT count(*) FROM public.audit;") == audit_count, "Repeat publication writes no audit event")
    require(release_snapshot(sql, OLD) == old_snapshot, "Publication preserves the Phase 11 row and audit count")
    require(call(prior, "GET", "/me/plan") == old_plan, "Phase 12 preserves the saved Phase 11 plan")
    require(call(prior, "GET", f"/content/{OLD}") == old_content, "Phase 11 remains accessible with identical content")
    print("PASSED: Phase 12 publication from Phase 11, repeat publication and saved Phase 11 plan", flush=True)


def check_inventory(guest, admin, sql):
    catalog = call(guest, "GET", "/catalog")
    ids = {goal["id"] for goal in catalog["goals"]}
    require(catalog["activeReleaseId"] == NEW and len(ids) == 19 and GOAL in ids,
            "Public catalog lists 19 goals including applied-data in the active Phase 12 release")
    content = call(admin, "GET", f"/content/{NEW}")
    lessons = content["sample"]["lessons"]
    require(len(lessons) == 126, "Admin sees all 126 lessons")
    require(sum(len(lesson["exercises"]) for lesson in lessons) == 352, "Admin sees all 352 exercises")
    require(int(sql(f"""
        SELECT jsonb_array_length(bundle->'codeLab') FROM public.content_releases WHERE release_id = '{NEW}';
    """)) == 47, "The published bundle stores 47 lab definitions")
    check_private_fields(content, "complete content")
    print("PASSED: 126 lessons, 352 exercises, 19 goals and 47 published labs", flush=True)


def check_prices(guest, admin, learner):
    def prices(offers):
        return {offer["goalId"]: (offer["price"], offer["currency"]) for offer in offers}

    offers = "/admin/access/offers"
    call(learner, "PUT", f"{offers}/{GOAL}", {"price": 1, "currency": "EGP"}, status=403)
    initial = prices(call(admin, "GET", offers))
    require(GOAL not in initial, "Phase 12 publishes no preset applied-data price")
    comparison = {"price": 51, "currency": "EGP"}
    call(admin, "PUT", f"{offers}/oop", comparison)
    expected = {**initial, "oop": (51, "EGP")}
    for value in (75, 82.5):
        call(admin, "PUT", f"{offers}/{GOAL}", {"price": value, "currency": "EGP"})
        expected[GOAL] = (value, "EGP")
        require(prices(call(admin, "GET", offers)) == expected, "Admin reads independent goal prices")
        require(prices(call(guest, "GET", "/catalog")["offers"]) == expected, "Public catalog reads independent goal prices")
    print("PASSED: independent admin-managed applied-data pricing", flush=True)


def check_scoped_content(learner, expected_lessons, goals):
    content = call(learner, "GET", f"/content/{NEW}")
    sample = content["sample"]
    require({lesson["id"] for lesson in sample["lessons"]} == set(expected_lessons), "Scoped lesson inventory")
    require([goal["id"] for goal in content["graph"]["goals"]] == goals, "Scoped goal inventory")
    downloads = {project["download"] for project in sample["projects"] if "download" in project}
    require(downloads == {DOWNLOAD}, "The applied-data ZIP link appears in the granted scope")
    check_private_fields(content, "scoped content")
    check_private_fields(call(learner, "GET", f"/content/{NEW}/lessons/{CAPSTONE}"), CAPSTONE)
    check_zip(learner, STARTER, 200)


def check_access(guest, learner, access):
    course = {"releaseId": NEW, "goalId": GOAL}
    capstone_url = f"/content/{NEW}/lessons/{CAPSTONE}"
    lab_url = f"/lab/exercises/{NEW}/stat-03"
    learner_name = "phase12_review_learner"
    expected = []
    for prefix, count in (
        ("core", 12), ("py", 12), ("data", 8), ("pd", 5), ("stat", 5), ("sql", 6), ("ana-sql", 5)
    ):
        expected.extend(lesson_range(prefix, count))
    expected.append(CAPSTONE)

    call(guest, "GET", f"/content/{NEW}", status=401)
    call(learner, "GET", f"/content/{NEW}", status=403)
    check_zip(guest, STARTER, 401)
    check_zip(learner, STARTER, 403)
    access("grant", learner_name, goalId=GOAL)
    preview = call(learner, "POST", "/plan-previews", course)
    require([step["lessonId"] for step in preview["steps"]] == expected and not preview["uncoveredSkillIds"],
            "Applied data plan includes exactly 54 lessons in prerequisite order")
    check_scoped_content(learner, expected, [GOAL])
    labs = call(learner, "GET", lab_url)
    require([(lab["id"], lab["language"]) for lab in labs["exercises"]] == [("stat-03-lab", "python")],
            "Statistics lab exposes its public Python metadata")
    check_private_fields(labs, "statistics lab metadata")
    access("revoke", learner_name, goalId=GOAL)
    call(learner, "GET", capstone_url, status=403)
    call(learner, "POST", "/plan-previews", course, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: 54-lesson applied-data plan, lab redaction, goal grant and ZIP revocation", flush=True)

    access("grant", learner_name, lessonId=CAPSTONE)
    check_scoped_content(learner, [CAPSTONE], [])
    call(learner, "GET", f"/content/{NEW}/lessons/ana-sql-05", status=403)
    call(learner, "GET", lab_url, status=403)
    call(learner, "POST", "/plan-previews", course, status=403)
    access("revoke", learner_name, lessonId=CAPSTONE)
    call(learner, "GET", capstone_url, status=403)
    check_zip(learner, STARTER, 403)
    print("PASSED: single-lesson grant and ZIP revocation, with learner answer redaction", flush=True)


def check_journey(origin, command, publish, sql):
    guest = Client(origin)
    admin_name = "phase12_review_admin"
    admin = register(origin, admin_name)
    learner = register(origin, "phase12_review_learner")
    prior = register(origin, "phase12_review_prior")
    command("--promote-admin", admin_name)
    admin.refresh_csrf()

    def access(action, name, **scope):
        call(admin, "POST", f"/admin/access/{action}", {"userName": name, **scope})

    check_upgrade(guest, prior, access, publish, sql)
    check_inventory(guest, admin, sql)
    check_prices(guest, admin, learner)
    check_access(guest, learner, access)


def run_isolated(assembly, pg, bundle, digest):
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

    def wait_for(process, ready, label, log_path):
        for _ in range(80):
            if process.poll() is not None:
                diagnostics = redact(log_path.read_text(encoding="utf-8", errors="replace"))
                raise RuntimeError(f"{label} exited ({process.returncode}): {diagnostics}")
            if ready():
                return
            time.sleep(.25)
        diagnostics = redact(log_path.read_text(encoding="utf-8", errors="replace"))
        raise RuntimeError(f"{label} did not become ready: {diagnostics}")

    def stop(process, timeout):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    with tempfile.TemporaryDirectory(prefix="masar-phase12-http-") as directory:
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
        origin = f"http://127.0.0.1:{api_port}"
        connection = f"Host=127.0.0.1;Port={db_port};Database=postgres;Timeout=5;"
        settings = dict(env, ASPNETCORE_ENVIRONMENT="Development", ASPNETCORE_URLS=origin,
                        MASAR_COMMERCIAL_ENABLED="true", MASAR_COMMERCIAL_SESSION_NAMESPACE="CommercialTest",
                        MASAR_CODE_LAB_ENABLED="false", MASAR_DATA_ROOT=str(scratch / "runtime"),
                        ConnectionStrings__Migration=connection + f"Username=qa_owner;Password={owner_password}",
                        ConnectionStrings__Masar=connection + f"Username=qa_app;Password={app_password}")

        def command(*arguments):
            return run(["dotnet", assembly, *arguments], cwd=scratch, env=settings)

        def sql(statement):
            return run([pg / "psql.exe", "-X", "-w", "-h", "127.0.0.1", "-p", db_port,
                        "-U", "qa_owner", "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1"],
                       input=statement.encode("ascii"), env=dict(env, PGPASSWORD=owner_password))

        def database_ready():
            return subprocess.run([pg / "pg_isready.exe", "-q", "-h", "127.0.0.1", "-p", str(db_port)],
                                  env=env, timeout=5).returncode == 0

        def api_ready():
            try:
                return Client(origin).request("GET", "/api/v1/health")[0] == 200
            except OSError:
                return False

        database_log = scratch / "postgres.log"
        with database_log.open("wb") as log:
            database = subprocess.Popen([pg / "postgres.exe", "-D", data, "-h", "127.0.0.1", "-p", str(db_port)],
                                        cwd=scratch, env=env, stdout=log, stderr=log)
        try:
            wait_for(database, database_ready, "Disposable PostgreSQL", database_log)
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
            for path in PREVIOUS:
                command("--publish-reviewed-curriculum", path, hashlib.sha256(path.read_bytes()).hexdigest())

            archive_dir = scratch / "wwwroot/projects"
            archive_dir.mkdir(parents=True)
            shutil.copyfile(PROJECTS / ZIP_NAME, archive_dir / ZIP_NAME)
            api_log = scratch / "api.log"
            with api_log.open("wb") as log:
                api = subprocess.Popen(["dotnet", str(assembly)], cwd=scratch,
                                       env={key: value for key, value in settings.items() if key != "ConnectionStrings__Migration"},
                                       stdout=log, stderr=log)
            try:
                wait_for(api, api_ready, "Isolated API", api_log)
                check_journey(origin, command, lambda: command("--publish-reviewed-curriculum", bundle, digest), sql)
            finally:
                stop(api, 15)
        finally:
            if database.poll() is None:
                try:
                    run([pg / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop"], env=env)
                finally:
                    stop(database, 10)


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
    require(hashlib.sha256(bundle.read_bytes()).hexdigest() == digest, "Phase 12 bundle hash differs from the reviewed digest")
    for path in (*PREVIOUS, PROJECTS / ZIP_NAME):
        require(path.is_file(), f"Missing required artifact {path}")

    # Preserve the ASCII junction path PostgreSQL's Windows binaries require.
    pg = args.postgres_bin.absolute()
    for name in ("initdb.exe", "postgres.exe", "pg_isready.exe", "psql.exe", "pg_ctl.exe"):
        require((pg / name).is_file(), f"Missing PostgreSQL binary {name}")
    run_isolated(assembly, pg, bundle, digest)


if __name__ == "__main__":
    main()
