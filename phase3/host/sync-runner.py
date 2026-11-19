"""Synchronize the three runner files in the project-owned guest over pinned SSH."""

import base64
import gzip
import inspect
import io
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tarfile
import zlib

PHASE = Path(__file__).resolve().parent.parent
TARGETS = {
    "broker.py": "/opt/nexora-code-runner/broker.py",
    "sandbox.py": "/opt/nexora-code-runner/sandbox.py",
    "nexora-code-runner.service": "/etc/systemd/system/nexora-code-runner.service",
}
MAX_COMPRESSED = 64 * 1024
MAX_UNPACKED = 128 * 1024


def make_archive():
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in TARGETS:
            path = PHASE / "runner" / name
            if not stat.S_ISREG(path.lstat().st_mode) or path.resolve() != path:
                raise ValueError("Unexpected runner source")
            with path.open("rb") as source:
                data = source.read(MAX_UNPACKED + 1)
            if len(data) > MAX_UNPACKED:
                raise ValueError("Runner source exceeds limit")
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    if archive.tell() > MAX_UNPACKED:
        raise ValueError("Runner archive exceeds limit")
    packed = gzip.compress(archive.getvalue(), mtime=0)
    if len(packed) > MAX_COMPRESSED:
        raise ValueError("Compressed runner archive exceeds limit")
    return packed


def guest_install():
    import fcntl
    import gzip
    import hashlib
    import http.client
    import io
    import json
    import os
    from pathlib import Path
    import socket
    import stat
    import subprocess
    import sys
    import tarfile
    import tempfile
    import time
    import uuid

    unit = "nexora-code-runner.service"

    def ensure(condition):
        if not condition:
            raise ValueError("Invalid synchronization input or guest state")

    def service(*args, timeout=75):
        return subprocess.run(["/usr/bin/systemctl", *args], check=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL).stdout.strip()

    def ensure_idle():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect("/var/run/docker.sock")
            sock.sendall(b"GET /v1.44/containers/json?all=1 HTTP/1.1\r\n"
                         b"Host: localhost\r\nConnection: close\r\n\r\n")
            with http.client.HTTPResponse(sock) as response:
                response.begin()
                ensure(response.status == 200)
                body = response.read(65537)
                ensure(len(body) <= 65536 and not response.length and json.loads(body) == [])

    def check_ready():
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            probe = http.client.HTTPConnection("127.0.0.1", 8787, timeout=2)
            try:
                probe.request("POST", "/v1/execute", body=b"")
                with probe.getresponse() as response:
                    if response.status == 401:
                        return
            except (OSError, http.client.HTTPException):
                pass
            finally:
                probe.close()
            time.sleep(1)
        raise TimeoutError("Guest runner readiness timed out")

    def replace(target, data):
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temp = Path(temporary.name)
            try:
                temporary.write(data)
                temporary.flush()
                os.fchown(temporary.fileno(), 0, 0)
                os.fchmod(temporary.fileno(), 0o644)
                os.fsync(temporary.fileno())
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)

    ensure(os.geteuid() == 0)
    os.umask(0o077)
    lock = os.open("/run/lock/nexora-code-runner-sync.lock",
                   os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    packed = sys.stdin.buffer.read(MAX_COMPRESSED + 1)
    ensure(len(packed) <= MAX_COMPRESSED)
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as compressed:
        unpacked = compressed.read(MAX_UNPACKED + 1)
    ensure(len(unpacked) <= MAX_UNPACKED)
    sources = {}
    with tarfile.open(mode="r:", fileobj=io.BytesIO(unpacked)) as archive:
        for entry in archive:
            ensure(entry.name in TARGETS and entry.name not in sources and
                   entry.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and
                   not entry.sparse and 0 < entry.size <= MAX_UNPACKED)
            with archive.extractfile(entry) as stream:
                sources[entry.name] = stream.read(entry.size)
            ensure(len(sources[entry.name]) == entry.size)
    ensure(sources.keys() == TARGETS.keys())
    changed = {}
    for name, data in sources.items():
        target = Path(TARGETS[name])
        metadata = target.lstat()
        ensure(target.resolve(strict=True) == target and stat.S_ISREG(metadata.st_mode)
               and metadata.st_uid == metadata.st_gid == 0 and metadata.st_nlink == 1
               and stat.S_IMODE(metadata.st_mode) == 0o644 and metadata.st_size <= MAX_UNPACKED)
        old = target.read_bytes()
        if hashlib.sha256(data).digest() != hashlib.sha256(old).digest():
            changed[name] = old
    if not changed:
        return "unchanged"

    try:
        ensure_idle()
    except Exception:
        return "idle-check-failed"
    state = service("show", "--property=ActiveState", "--value", unit, timeout=15)
    ensure(state in (b"active", b"inactive", b"failed"))
    active = state == b"active"
    backups = Path("/var/backups/nexora-code-runner") / uuid.uuid4().hex
    backups.mkdir(mode=0o700, parents=True)
    for name, original in changed.items():
        (backups / name).write_bytes(original)
    installed = []
    try:
        service("stop", unit)
        ensure_idle()
        for name in changed:
            replace(Path(TARGETS[name]), sources[name])
            installed.append(name)
        if unit in installed:
            service("daemon-reload", timeout=30)
        if active:
            service("start", unit)
            check_ready()
        return "updated"
    except Exception:
        try:
            if installed and active:
                service("stop", unit)
            for name in reversed(installed):
                replace(Path(TARGETS[name]), (backups / name).read_bytes())
            if unit in installed:
                service("daemon-reload", timeout=30)
            if active:
                service("start", unit)
                check_ready()
        except Exception:
            return "rollback-failed"
        return "rolled-back"


def main():
    # Send only the small installer as a command argument; the archive streams on stdin.
    source = (f"TARGETS={TARGETS!r}\nMAX_COMPRESSED={MAX_COMPRESSED}\nMAX_UNPACKED={MAX_UNPACKED}\n"
              + inspect.getsource(guest_install)
              + "\ntry:\n    print(guest_install())\nexcept Exception:\n    print('guest-check-failed')\n")
    encoded = base64.b64encode(zlib.compress(source.encode("utf-8"))).decode("ascii")
    command = "sudo -n /usr/bin/python3 -I -B -c " + shlex.quote(
        f"import base64,zlib;exec(zlib.decompress(base64.b64decode('{encoded}')))")
    vm = PHASE / ".local" / "runner-vm"
    ssh = ["ssh.exe", "-T", "-F", "NUL", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
           "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=known_hosts",
           "-o", "GlobalKnownHostsFile=NUL", "-o", "IdentitiesOnly=yes",
           "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
           "-p", "2227", "-i", "vm-operator", "nexora-operator@127.0.0.1", command]
    response = subprocess.run(ssh, cwd=vm, input=make_archive(), stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=720)
    messages = {
        b"unchanged": "Guest runner files already match.",
        b"updated": "Guest runner files synchronized.",
        b"idle-check-failed": "Guest containers are present or idle state could not be verified.",
        b"rolled-back": "Synchronization failed. Previous runner files restored.",
        b"rollback-failed": "Synchronization and recovery failed. Guest requires inspection.",
        b"guest-check-failed": "Guest synchronization validation failed.",
    }
    status = response.stdout.strip()
    if response.returncode or status not in messages:
        raise RuntimeError("Guest synchronization transport failed")
    print(messages[status])
    return 0 if status in (b"unchanged", b"updated") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        sys.exit("Runner synchronization could not be confirmed.")
