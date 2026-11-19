"""Fixed Docker/runsc profile for the NEXORA CODE console runner."""

import http.client
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass

MAX_CODE = 32 * 1024
MAX_STDIN = 8 * 1024
MAX_OUTPUT = 16 * 1024
RUN_SECONDS = 4
DOCKER_SECONDS = 10
CLEANUP_CONTROL_SECONDS = 3
CREATE_SECONDS = 10
STARTUP_SECONDS = 10
DOCKER_CLEANUP_SECONDS = 16
DOCKER_SOCKET = "/var/run/docker.sock"
MAX_HOST_INFO = 1024 * 1024
DOCKER_PATH = "/usr/local/bin:/usr/bin:/bin"
OWNER = "org.nexora.code.phase3.runner=1"
NAME = re.compile(r"nexora-code-[0-9a-f]{32}")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,254}@sha256:[0-9a-f]{64}")
READY_MARKER = b"NEXORA-RUNNER-READY-v1\n"

# The only arguments passed to the images are these trusted bootstraps. Code and
# stdin arrive in a byte-length frame through the attached process's stdin.
PYTHON_BOOT = """\
import os, struct, sys
source_size, input_size = struct.unpack('!II', sys.stdin.buffer.read(8))
assert source_size <= 32768 and input_size <= 8192
source = sys.stdin.buffer.read(source_size)
data = sys.stdin.buffer.read(input_size)
assert len(source) == source_size and len(data) == input_size
os.umask(0o077)
with open('/tmp/main.py', 'xb') as file:
    file.write(source)
with open('/tmp/input', 'xb') as file:
    file.write(data)
fd = os.open('/tmp/input', os.O_RDONLY)
os.dup2(fd, 0)
os.close(fd)
os.write(2, %r)
os.execv(sys.executable, [sys.executable, '-I', '-B', '-u', '-X', 'utf8', '/tmp/main.py'])
""" % READY_MARKER

NODE_BOOT = """\
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
function read(size) {
    const data = Buffer.alloc(size);
    let offset = 0;
    while (offset < size) {
        const count = fs.readSync(0, data, offset, size - offset, null);
        if (count === 0) throw new Error('Incomplete input frame');
        offset += count;
    }
    return data;
}
const header = read(8);
const sourceSize = header.readUInt32BE(0);
const inputSize = header.readUInt32BE(4);
if (sourceSize > 32768 || inputSize > 8192) throw new Error('Invalid input frame');
process.umask(0o077);
fs.writeFileSync('/tmp/main.cjs', read(sourceSize), {flag: 'wx'});
fs.writeFileSync('/tmp/input', read(inputSize), {flag: 'wx'});
const input = fs.openSync('/tmp/input', 'r');
fs.writeSync(2, %s);
const result = spawnSync(process.execPath, ['--max-old-space-size=64', '/tmp/main.cjs'], {
    stdio: [input, 'inherit', 'inherit'],
});
fs.closeSync(input);
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
""" % json.dumps(READY_MARKER.decode("ascii"))

PROGRAMS = {
    "python": ("/usr/local/bin/python", "-I", "-B", "-X", "utf8", "-c", PYTHON_BOOT),
    "javascript": ("/usr/local/bin/node", "--max-old-space-size=32", "-e", NODE_BOOT),
}


@dataclass(frozen=True)
class Job:
    language: str
    code: bytes
    stdin: bytes

    def frame(self):
        return struct.pack("!II", len(self.code), len(self.stdin)) + self.code + self.stdin


@dataclass(frozen=True)
class Result:
    status: str
    stdout: str = ""
    stderr: str = ""


class InfrastructureError(RuntimeError):
    pass


def create_args(name, image, language):
    if not NAME.fullmatch(name) or not IMAGE.fullmatch(image):
        raise InfrastructureError("Invalid container name or image digest reference")
    entrypoint, *args = PROGRAMS[language]
    return [
        "container", "create", "--name", name, "--label", OWNER,
        "--runtime=runsc", "--pull=never", "--network=none", "--ipc=none",
        "--cgroupns=private", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--user=65532:65532",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=4m,mode=1777",
        "--memory=192m", "--memory-swap=192m", "--cpus=0.5", "--pids-limit=32",
        "--ulimit=nproc=32:32", "--ulimit=nofile=128:128", "--ulimit=core=0:0",
        "--log-driver=none", "--no-healthcheck", "--restart=no", "--interactive",
        "--workdir=/tmp", "--env=HOME=/tmp", "--env=TMPDIR=/tmp", "--env=LANG=C.UTF-8",
        "--entrypoint", entrypoint, image, *args,
    ]


class Docker:
    def __init__(self, executable, config_dir):
        self.prefix = [executable, f"--host=unix://{DOCKER_SOCKET}", "--config", config_dir]
        self.env = {"PATH": DOCKER_PATH, "LANG": "C.UTF-8"}

    def host_info(self, *, timeout):
        # Only daemon metadata is needed here. docker info also discovers CLI plugins.
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(DOCKER_SOCKET)
                sock.sendall(b"GET /v1.44/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                with http.client.HTTPResponse(sock) as response:
                    response.begin()
                    if response.status != 200:
                        raise InfrastructureError(f"Docker host info returned HTTP {response.status}")
                    if response.length is not None and response.length > MAX_HOST_INFO:
                        raise InfrastructureError("Docker host info exceeds size limit")
                    data = response.read(MAX_HOST_INFO + 1)
                    if len(data) > MAX_HOST_INFO:
                        raise InfrastructureError("Docker host info exceeds size limit")
                    if response.length:
                        raise InfrastructureError("Docker host info response was incomplete")
            return json.loads(data)
        except (OSError, http.client.HTTPException, ValueError, RecursionError) as exc:
            raise InfrastructureError("Could not read Docker host info") from exc

    def control(self, *args, timeout=DOCKER_SECONDS):
        # Used exclusively for trusted, bounded daemon metadata and control responses.
        try:
            return subprocess.run(
                [*self.prefix, *args], env=self.env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                check=False, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise InfrastructureError("Docker control command timed out") from exc
        except OSError as exc:
            raise InfrastructureError("Docker control command unavailable") from exc

    def metadata(self, *args, timeout=DOCKER_SECONDS):
        command = self.control(*args, timeout=timeout)
        if command.returncode != 0:
            raise InfrastructureError("Docker metadata command failed")
        try:
            return json.loads(command.stdout)
        except (ValueError, UnicodeError) as exc:
            raise InfrastructureError("Invalid Docker metadata") from exc

    def start(self, name):
        return subprocess.Popen(
            [*self.prefix, "container", "start", "--attach", "--interactive", name],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )

    def owned_names(self, name=None, *, timeout=DOCKER_SECONDS):
        args = ["container", "ls", "--all", "--filter", f"label={OWNER}", "--format", "{{.Names}}"]
        if name is not None:
            args.extend(["--filter", f"name=^/{name}$"])
        listed = self.control(*args, timeout=timeout)
        if listed.returncode != 0:
            raise InfrastructureError("Could not verify runner container cleanup")
        names = listed.stdout.decode("ascii", errors="replace").splitlines()
        if any(not NAME.fullmatch(item) for item in names):
            raise InfrastructureError("Unexpected name among labeled runner containers")
        return names

    def remove(self, name):
        if not NAME.fullmatch(name):
            raise InfrastructureError("Invalid runner container name")
        deadline = time.monotonic() + DOCKER_CLEANUP_SECONDS
        # Match both our label and the generated name before force-removing.
        if name not in self.owned_names(name, timeout=CLEANUP_CONTROL_SECONDS):
            return
        # Docker can wait for a task exit event and retry SIGKILL during rm.
        # Keep time for a separate check even if the removal command times out.
        removal_error = None
        try:
            self.control("container", "rm", "--force", "--volumes", name,
                         timeout=deadline - time.monotonic() - CLEANUP_CONTROL_SECONDS)
        except InfrastructureError as error:
            removal_error = error
        remaining = min(CLEANUP_CONTROL_SECONDS, deadline - time.monotonic())
        if remaining <= 0:
            raise InfrastructureError("Container cleanup deadline expired") from removal_error
        if name in self.owned_names(name, timeout=remaining):
            if removal_error is not None:
                raise InfrastructureError(f"Runner container survived cleanup: {removal_error}") from removal_error
            raise InfrastructureError("Runner container survived cleanup")

    def sweep(self):
        for name in self.owned_names():
            self.remove(name)


class Output:
    def __init__(self, limit):
        self.limit = limit
        self.lock = threading.Lock()
        self.overflow = threading.Event()
        self.failed = threading.Event()
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.remaining = limit

    def append(self, stream, data):
        with self.lock:
            if len(data) > self.remaining:
                self.overflow.set()
            self.buffers[stream].extend(data[:self.remaining])
            self.remaining -= min(len(data), self.remaining)

    def read(self, stream, pipe):
        try:
            while not self.overflow.is_set():
                data = pipe.read(4096)
                if not data:
                    break
                self.append(stream, data)
        except OSError:
            self.failed.set()

    def result(self, status):
        strings = []
        remaining = self.limit
        for data in self.buffers.values():
            utf8 = data.decode("utf-8", errors="replace").encode("utf-8")
            if len(utf8) > remaining:
                self.overflow.set()
            value = utf8[:remaining].decode("utf-8", errors="ignore")
            strings.append(value)
            remaining -= len(value.encode("utf-8"))
        if status != "timed_out" and self.overflow.is_set():
            status = "output_limit"
        return Result(status, *strings)


def write_frame(pipe, frame, failed):
    try:
        remaining = memoryview(frame)
        while remaining:
            remaining = remaining[pipe.write(remaining):]
    except BrokenPipeError:
        pass  # Docker's exit state will distinguish an unsuccessful start.
    except OSError:
        failed.set()
    finally:
        pipe.close()


def collect(process, frame, seconds=RUN_SECONDS, limit=MAX_OUTPUT, *, startup_seconds=None):
    """Drain both CLI pipes concurrently and stop capture at the combined limit."""
    output = Output(limit)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    started = time.monotonic()
    startup_finished = threading.Event()
    ready_at = None

    def read_stderr():
        nonlocal ready_at
        if startup_seconds is not None:
            # Only the trusted bootstrap runs before this prefix. Consume exactly
            # its bytes once; all subsequent stderr is ordinary learner output.
            offset = 0
            try:
                while offset < len(READY_MARKER):
                    part = process.stderr.read(len(READY_MARKER) - offset)
                    if not part or not READY_MARKER.startswith(part, offset):
                        return
                    offset += len(part)
                ready_at = time.monotonic()
            except OSError:
                return
            finally:
                startup_finished.set()
        output.read("stderr", process.stderr)

    readers = [
        threading.Thread(target=output.read, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stderr, daemon=True),
    ]
    writer = threading.Thread(target=write_frame, args=(process.stdin, frame, output.failed), daemon=True)
    deadline = started + seconds
    status = "completed"
    try:
        for worker in [*readers, writer]:
            worker.start()
        if startup_seconds is not None:
            startup_deadline = started + startup_seconds
            startup_finished.wait(max(0, startup_deadline - time.monotonic()))
            if ready_at is None or ready_at > startup_deadline:
                raise InfrastructureError("Runner bootstrap did not confirm readiness")
            deadline = ready_at + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timed_out"
                break
            if process.poll() is not None:
                # A scheduling stall while polling must not accept a late-observed exit.
                if time.monotonic() > deadline:
                    status = "timed_out"
                break
            if output.overflow.wait(min(remaining, 0.02)):
                break
    finally:
        if process.poll() is None:
            process.kill()
        drain_deadline = time.monotonic() + 1
        process.wait(timeout=1)
        for worker in [*readers, writer]:
            worker.join(timeout=max(0, drain_deadline - time.monotonic()))
        process.stdout.close()
        process.stderr.close()
    if output.failed.is_set() or any(worker.is_alive() for worker in [*readers, writer]):
        raise InfrastructureError("Could not capture runner output")
    if process.returncode != 0 and status == "completed":
        status = "code_error"
    return output.result(status)


class Sandbox:
    def __init__(self, docker, images):
        self.docker = docker
        self.images = images
        self.unhealthy = threading.Event()

    def execute(self, job, *, run_seconds=RUN_SECONDS):
        if self.unhealthy.is_set():
            return Result("infrastructure_error")
        name = f"nexora-code-{uuid.uuid4().hex}"
        result = Result("infrastructure_error")
        try:
            created = self.docker.control(*create_args(name, self.images[job.language], job.language), timeout=CREATE_SECONDS)
            if created.returncode != 0:
                raise InfrastructureError("Container creation failed")
            process = self.docker.start(name)
            result = collect(process, job.frame(), seconds=run_seconds, startup_seconds=STARTUP_SECONDS)
            if result.status in ("completed", "code_error"):
                state = self.docker.metadata("container", "inspect", "--format", "{{json .State}}", name)
                if (not isinstance(state, dict) or state.get("Status") != "exited"
                        or state.get("Error") != "" or state.get("ExitCode") != process.returncode):
                    raise InfrastructureError("Container did not report a valid exit state")
        except (InfrastructureError, OSError, subprocess.TimeoutExpired):
            result = Result("infrastructure_error")
        finally:
            try:
                self.docker.remove(name)
            except InfrastructureError as error:
                print(f"Runner container cleanup failed: {error}", file=sys.stderr, flush=True)
                self.unhealthy.set()
                result = Result("infrastructure_error")
        return result
