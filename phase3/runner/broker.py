"""Private, loopback-only HTTP broker for the dedicated Linux sandbox host."""

import argparse
import hmac
import json
import os
import re
import shutil
import signal
import socket
import sys
import tempfile
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sandbox import (
    DOCKER_PATH, IMAGE, MAX_CODE, MAX_STDIN, PROGRAMS, Docker,
    InfrastructureError, Job, Sandbox,
)

PORT = 8787
MAX_BODY = 6 * (MAX_CODE + MAX_STDIN) + 256
MAX_CONNECTIONS = 8
MAX_JOBS = 2
PREFLIGHT_SECONDS = 15
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
IMAGE_VARIABLES = {
    "python": "NEXORA_RUNNER_PYTHON_IMAGE",
    "javascript": "NEXORA_RUNNER_JAVASCRIPT_IMAGE",
}


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON fields")
    return result


def reject_number(_):
    raise ValueError("Expected text fields")


def parse_job(body):
    value = json.loads(
        body.decode("utf-8"), object_pairs_hook=unique_fields,
        parse_int=reject_number, parse_float=reject_number, parse_constant=reject_number,
    )
    if not isinstance(value, dict) or value.keys() != {"language", "code", "stdin"}:
        raise ValueError("Expected language, code and stdin")
    if not all(isinstance(field, str) for field in value.values()):
        raise ValueError("Expected text fields")
    if value["language"] not in PROGRAMS:
        raise ValueError("Unsupported language")
    code = value["code"].encode("utf-8")
    stdin = value["stdin"].encode("utf-8")
    if len(code) > MAX_CODE or len(stdin) > MAX_STDIN or b"\x00" in code:
        raise ValueError("Invalid code or stdin")
    return Job(value["language"], code, stdin)


class Broker(ThreadingHTTPServer):
    daemon_threads = False
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, address, token, sandbox):
        self.authorization = f"Bearer {token}".encode("ascii")
        self.sandbox = sandbox
        self.connections = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.jobs = threading.BoundedSemaphore(MAX_JOBS)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.connections.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def log_message(self, format, *args):
        # Request lines and learner data do not belong in broker logs.
        pass

    def reply(self, status, value):
        payload = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        self.close_connection = True
        if self.path != "/v1/execute":
            self.reply(404, {"error": "not_found"})
            return
        auth = self.headers.get_all("Authorization", [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("latin-1"), self.server.authorization):
            self.reply(401, {"error": "unauthorized"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Content-Encoding")
                or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0])):
            self.reply(400, {"error": "invalid_request"})
            return
        length = int(lengths[0])
        if length > MAX_BODY:
            self.reply(413, {"error": "body_too_large"})
            return
        if len(self.headers.get_all("Content-Type", [])) != 1 or self.headers.get_content_type() != "application/json":
            self.reply(415, {"error": "expected_json"})
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request")
            job = parse_job(body)
        except (ValueError, RecursionError, socket.timeout):
            self.reply(400, {"error": "invalid_request"})
            return
        if not self.server.jobs.acquire(blocking=False):
            self.reply(503, {"error": "runner_busy"})
            return
        try:
            result = self.server.sandbox.execute(job)
            self.reply(200, asdict(result))
        finally:
            self.server.jobs.release()


def load_images(environment):
    images = {language: environment.get(variable, "") for language, variable in IMAGE_VARIABLES.items()}
    for language, image in images.items():
        if not IMAGE.fullmatch(image):
            raise InfrastructureError(f"Set {IMAGE_VARIABLES[language]} to a reviewed image digest reference")
    return images


def validate_host(info):
    if (not isinstance(info, dict) or info.get("OSType") != "linux" or info.get("CgroupVersion") != "2"
            or info.get("CgroupDriver") not in {"cgroupfs", "systemd"}):
        raise InfrastructureError("Docker must use Linux and cgroup v2")
    for feature in ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit"):
        if info.get(feature) is not True:
            raise InfrastructureError(f"Docker is missing the {feature} controller")
    runsc = info.get("Runtimes", {}).get("runsc", {})
    if Path(runsc.get("path", "")).name != "runsc" or runsc.get("runtimeArgs"):
        raise InfrastructureError("Register the gVisor runsc binary as runtime runsc with its default options")


PYTHON_PROBE = b"""\
import os, resource, sys
assert os.getuid() == 65532 and os.getgid() == 65532
status = dict(line.split(':', 1) for line in open('/proc/self/status') if ':' in line)
assert int(status['CapEff'], 16) == int(status['CapBnd'], 16) == 0
assert int(status['NoNewPrivs']) == 1
assert os.statvfs('/').f_flag & os.ST_RDONLY
tmp = os.statvfs('/tmp')
assert 0 < tmp.f_blocks * tmp.f_frsize <= 4 * 1024 * 1024
assert resource.getrlimit(resource.RLIMIT_NPROC) == (32, 32)
assert not os.path.exists('/var/run/docker.sock')
assert 'NEXORA_RUNNER_BEARER_TOKEN' not in os.environ
interfaces = open('/proc/net/dev').read().splitlines()[2:]
assert all(line.split(':', 1)[0].strip() == 'lo' for line in interfaces)
print(sys.stdin.read(), end='')
"""

NODE_PROBE = b"""\
const fs = require('node:fs');
if (process.getuid() !== 65532 || process.getgid() !== 65532) process.exit(1);
const status = fs.readFileSync('/proc/self/status', 'utf8');
if (!/^CapEff:\\s+0+$/m.test(status) || !/^CapBnd:\\s+0+$/m.test(status) || !/^NoNewPrivs:\\s+1$/m.test(status)) process.exit(1);
if (fs.existsSync('/var/run/docker.sock') || process.env.NEXORA_RUNNER_BEARER_TOKEN) process.exit(1);
process.stdout.write(fs.readFileSync(0, 'utf8'));
"""


def preflight(docker, images):
    info = docker.host_info(timeout=PREFLIGHT_SECONDS)
    validate_host(info)
    docker.sweep()
    for language, image in images.items():
        volumes = docker.metadata("image", "inspect", "--format", "{{json .Config.Volumes}}", image)
        if volumes not in (None, {}):
            raise InfrastructureError(f"The {language} image declares volumes")
    sandbox = Sandbox(docker, images)
    payload = "اختبار المُشغّل\n".encode("utf-8")
    for language, program in (("python", PYTHON_PROBE), ("javascript", NODE_PROBE)):
        # These fixed probes also cover cold Docker/runsc startup.
        result = sandbox.execute(Job(language, program, payload), run_seconds=PREFLIGHT_SECONDS)
        if result.status != "completed" or result.stdout.encode("utf-8") != payload or result.stderr:
            raise InfrastructureError(f"The {language} sandbox preflight failed ({result.status})")
    return sandbox


def serve(token, sandbox):
    stopping = threading.Event()

    def stop(_signal, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with Broker(("127.0.0.1", PORT), token, sandbox) as server:
        server.timeout = 0.25
        print(f"Runner ready on 127.0.0.1:{PORT}", flush=True)
        while not stopping.is_set() and not sandbox.unhealthy.is_set():
            server.handle_request()
    if sandbox.unhealthy.is_set():
        raise InfrastructureError("Container cleanup could not be confirmed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--preflight", action="store_true", help="check both images, then exit")
    actions.add_argument("--cleanup-owned", action="store_true", help="remove abandoned runner containers")
    options = parser.parse_args()
    if sys.platform != "linux" or re.search(r"microsoft|wsl", os.uname().release, re.I):
        raise InfrastructureError("This runner requires a dedicated native Linux host")

    import fcntl

    executable = shutil.which("docker", path=DOCKER_PATH)
    if executable is None:
        raise InfrastructureError("Docker CLI was not found in the system path")
    with open("/run/nexora-code-runner/owner.lock", "a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InfrastructureError("Another runner process owns the host lock") from exc
        with tempfile.TemporaryDirectory(prefix="nexora-docker-") as config_dir:
            docker = Docker(executable, config_dir)
            if options.cleanup_owned:
                docker.sweep()
                return
            images = load_images(os.environ)
            token = os.environ.get("NEXORA_RUNNER_BEARER_TOKEN", "")
            if not options.preflight and not TOKEN.fullmatch(token):
                raise InfrastructureError("Set a private NEXORA_RUNNER_BEARER_TOKEN")
            sandbox = preflight(docker, images)
            if options.preflight:
                print("Both runsc console profiles passed preflight")
            else:
                serve(token, sandbox)


if __name__ == "__main__":
    try:
        main()
    except (InfrastructureError, OSError) as error:
        sys.exit(f"Runner unavailable: {error}")
