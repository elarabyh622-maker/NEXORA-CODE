"""Run browser acceptance against both references and the published starter ZIPs.

Install the reference npm dependencies and Phase 9 Python requirements first.
Run using the Phase 9 virtualenv. Set PLAYWRIGHT_CORE to an installed module
and BROWSER_EXECUTABLE to a Chromium-based browser when needed.
"""
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
from contextlib import contextmanager
from urllib.request import urlopen
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOCAL = HERE / ".local"
VITE_SERVER = """
import { createServer } from 'vite';
const server = await createServer({
  logLevel: 'silent', server: { host: '127.0.0.1', port: 0, open: false }
});
await server.listen();
process.stdout.write(String(server.httpServer.address().port) + '\\n');
"""


def serve_backend(folder):
    # All imports resolve to the disposable copy of the service.
    sys.path.insert(0, str(folder))
    import uvicorn
    from catalogue import auth, store
    from catalogue.app import create_app

    database = folder / "browser.sqlite3"
    store.initialize(database)
    password = json.loads(sys.stdin.readline())
    for role in ("admin", "reader"):
        auth.create_user(database, role, password, role)
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        print(server_socket.getsockname()[1], flush=True)
        uvicorn.Server(uvicorn.Config(create_app(database), log_level="error")).run(sockets=[server_socket])


@contextmanager
def server(cmd, folder, env, password=None):
    proc = subprocess.Popen(cmd, cwd=folder, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        if password is not None:
            proc.stdin.write(json.dumps(password) + "\n")
        proc.stdin.close()
        port = int(proc.stdout.readline().strip())
        origin = f"http://127.0.0.1:{port}"
        for attempt in range(100):
            try:
                with urlopen(origin, timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if proc.poll() is not None or attempt == 99:
                raise RuntimeError("Local browser test server failed to start")
            time.sleep(.1)
        yield origin
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def browser(origin, case, mode, password):
    result = subprocess.run(
        ["node", str(HERE / "check-browser.cjs"), origin, case, mode],
        input=password, text=True, capture_output=True, encoding="utf-8", timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"{case}/{mode}: {result.stderr.strip()}")
    row = json.loads(result.stdout)
    print(f"PASS {case}/{mode} ({len(row['checks'])} browser scenarios)", flush=True)
    return row


def unzip(archive_path, destination, reference):
    destination.mkdir()
    with ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if not (destination / name).resolve().is_relative_to(destination):
                raise ValueError(f"Unexpected archive path: {name}")
        archive.extractall(destination)
    if (destination / "package-lock.json").read_bytes() != (reference / "package-lock.json").read_bytes():
        raise ValueError("Published starter and installed reference have different dependency locks")
    # Use the installed dependency tree without copying authored project files.
    shutil.copytree(reference / "node_modules", destination / "node_modules",
                    ignore=shutil.ignore_patterns(".vite", ".vite-temp"))
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


def check_run():
    LOCAL.mkdir(exist_ok=True)
    rows = []
    archives = REPO / "phase2/apps/web/public/projects"
    with tempfile.TemporaryDirectory(prefix="browser-", dir=LOCAL) as temp:
        work = Path(temp).resolve()
        for language, filename in (("js", "react-starter-v1.zip"), ("ts", "typescript-starter-v1.zip")):
            reference = HERE / f"reference-{language}"
            starter = work / f"starter-{language}"
            archive_digest = unzip(archives / filename, starter, reference)
            env = {**os.environ, "VITE_DATA_SOURCE": "mock"}
            for project in (reference, starter):
                with server(["node", "--input-type=module", "-e", VITE_SERVER], project, env) as origin:
                    row = browser(origin, project.name, "mock", "training")
                    if project == starter:
                        row.update(archive=filename, sha256=archive_digest)
                    rows.append(row)
            backend = work / f"backend-{language}"
            shutil.copytree(REPO / "phase9/project/reference/catalogue", backend / "catalogue",
                            ignore=shutil.ignore_patterns("__pycache__", "static"))
            dest = backend / "catalogue/static"
            env["VITE_DATA_SOURCE"] = "api"
            subprocess.run(["node", "node_modules/vite/bin/vite.js", "build", "--outDir", str(dest)],
                           cwd=reference, env=env, check=True, timeout=120)
            password = secrets.token_urlsafe(32)
            with server([sys.executable, str(Path(__file__).resolve()), "--serve", str(backend)],
                        backend, env, password) as origin:
                rows.append(browser(origin, reference.name, "api", password))
    report = LOCAL / "browser-acceptance.json"
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(len(row['checks']) for row in rows)} passed across {len(rows)} runs. {report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve_backend(args.serve.resolve())
    else:
        check_run()
