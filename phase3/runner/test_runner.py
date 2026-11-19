"""Broker checks using fixed fixtures and an in-process fake sandbox."""

import http.client
import io
import json
import struct
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from broker import MAX_BODY, PREFLIGHT_SECONDS, Broker, load_images, parse_job, validate_host
from sandbox import (
    CLEANUP_CONTROL_SECONDS, DOCKER_SOCKET, MAX_CODE, MAX_HOST_INFO, MAX_STDIN, OWNER, READY_MARKER,
    Docker, InfrastructureError, Job, Result, Sandbox, collect, create_args,
)

PIN = "example.invalid/lab@sha256:" + "a" * 64
AUTH = "test_" + "a" * 38
NAME = "nexora-code-" + "c" * 32


def document(code="print(input())", stdin="مرحبا\n", language="python"):
    return json.dumps({"language": language, "code": code, "stdin": stdin}).encode()


def fixture(program):
    return subprocess.Popen(
        [sys.executable, "-I", "-B", "-u", "-c", program],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )


class ValidationTests(unittest.TestCase):
    def test_utf8_lengths_and_frame(self):
        job = parse_job(document(code="ي" * (MAX_CODE // 2), stdin="i" * MAX_STDIN))
        self.assertEqual(struct.unpack("!II", job.frame()[:8]), (MAX_CODE, MAX_STDIN))
        self.assertEqual(job.frame()[8:], job.code + job.stdin)

    def test_invalid_payloads(self):
        cases = [
            document(code="ي" * (MAX_CODE // 2 + 1)), document(stdin="i" * (MAX_STDIN + 1)),
            document(code="nul\0"), document(code="\ud800"), document(language="node"),
            document(code=[1]), b'{"language":"python","code":"1","stdin":"","stdin":""}',
            b'{"language":"python","code":"1","stdin":"","runtime":"runc"}', b"\xff",
        ]
        for body in cases:
            with self.subTest(body_size=len(body)), self.assertRaises(ValueError):
                parse_job(body)

    def test_no_image_tag_or_cli_options(self):
        for image in ("python:latest", "--runtime=runc", "python@sha256:123"):
            with self.subTest(image=image), self.assertRaises(InfrastructureError):
                load_images({"NEXORA_RUNNER_PYTHON_IMAGE": image, "NEXORA_RUNNER_JAVASCRIPT_IMAGE": PIN})

    def test_fixed_profile(self):
        for language, binary in (("python", "python"), ("javascript", "node")):
            with self.subTest(language=language):
                args = create_args(NAME, PIN, language)
                self.assertEqual(args[:6], ["container", "create", "--name", NAME, "--label", OWNER])
                for flag in (
                    "--runtime=runsc", "--pull=never", "--network=none", "--ipc=none",
                    "--cgroupns=private", "--cap-drop=ALL", "--read-only",
                    "--security-opt=no-new-privileges", "--user=65532:65532",
                    "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=4m,mode=1777",
                    "--memory=192m", "--memory-swap=192m", "--cpus=0.5", "--pids-limit=32",
                    "--ulimit=nproc=32:32", "--restart=no", "--log-driver=none", "--no-healthcheck",
                ):
                    self.assertIn(flag, args)
                self.assertEqual(args[args.index("--entrypoint") + 1:args.index(PIN)], [f"/usr/local/bin/{binary}"])
                self.assertFalse(any(arg.startswith(("--privileged", "--mount", "--volume", "--device")) for arg in args))

    def test_host_gate(self):
        good = dict(OSType="linux", CgroupVersion="2", CgroupDriver="systemd", MemoryLimit=True,
                    SwapLimit=True, CpuCfsQuota=True, PidsLimit=True, Runtimes={"runsc": {"path": "/bin/runsc"}})
        validate_host(good)
        for invalid in (dict(PidsLimit=False), dict(CgroupVersion="1"), dict(Runtimes={}),
                        dict(Runtimes={"runsc": {"path": "/bin/runc"}}),
                        dict(Runtimes={"runsc": {"path": "/bin/runsc", "runtimeArgs": ["--ignore-cgroups"]}})):
            with self.subTest(invalid=invalid), self.assertRaises(InfrastructureError):
                validate_host(good | invalid)


class CaptureTests(unittest.TestCase):
    def test_delayed_fragmented_readiness_preserves_entire_learner_budget(self):
        program = (
            f"import os, time; time.sleep(0.4); os.write(2, {READY_MARKER[:5]!r}); "
            f"time.sleep(0.05); os.write(2, {READY_MARKER[5:]!r} + b'err'); os.write(1, b'ok')"
        )
        self.assertEqual(collect(fixture(program), b"", seconds=0.2, startup_seconds=3, limit=5),
                         Result("completed", "ok", "err"))

    def test_bootstrap_must_confirm_on_stderr_before_deadline(self):
        programs = [
            "pass",
            f"import os; os.write(1, {READY_MARKER!r})",
            f"import os; os.write(2, b'warning' + {READY_MARKER!r})",
            f"import os; os.write(2, {READY_MARKER[:-1]!r})",
            f"import os, time; time.sleep(2); os.write(2, {READY_MARKER!r})",
        ]
        for program in programs:
            with self.subTest(program=program), self.assertRaisesRegex(InfrastructureError, "readiness"):
                collect(fixture(program), b"", seconds=1, startup_seconds=0.4)

    def test_learner_marker_is_output_and_cannot_extend_deadline(self):
        program = (
            f"import os, time\nmarker = {READY_MARKER!r}\nos.write(2, marker)\n"
            "for i in range(12):\n    os.write(2, marker)\n    time.sleep(0.1)"
        )
        result = collect(fixture(program), b"", seconds=0.35, startup_seconds=3)
        self.assertEqual(result.status, "timed_out")
        self.assertTrue(result.stderr.startswith(READY_MARKER.decode("ascii")))

    def test_combined_cap_reached_with_readiness_and_immediate_exit(self):
        program = f"import os; os.write(2, {READY_MARKER!r} + b'aaaa'); os.write(1, b'bbbb')"
        result = collect(fixture(program), b"", limit=7, startup_seconds=3)
        self.assertEqual(result.status, "output_limit")
        self.assertEqual(len(result.stdout) + len(result.stderr), 7)

    def test_exit_observed_after_budget_cannot_be_accepted_as_completed(self):
        process = fixture("print('ok')")
        original_poll = process.poll
        delayed = False
        def delayed_poll():
            nonlocal delayed
            if not delayed:
                delayed = True
                time.sleep(0.25)
            return original_poll()
        with patch.object(process, "poll", side_effect=delayed_poll):
            self.assertEqual(collect(process, b"", seconds=0.1).status, "timed_out")

    def test_preserves_input_stdout_stderr_and_exit(self):
        program = "import sys; print(sys.stdin.read(), end=''); sys.stderr.buffer.write(b'error\\n'); sys.exit(3)"
        result = collect(fixture(program), b"sample")
        self.assertEqual(result, Result("code_error", "sample", "error\n"))

    def test_exact_cap(self):
        self.assertEqual(collect(fixture("print('a'*32, end='')"), b"", limit=32), Result("completed", "a" * 32))

    def test_combined_cap(self):
        result = collect(fixture("import os; os.write(1, b'a'*8192); os.write(2, b'b'*8192); os.write(1, b'c'*32768)"), b"")
        self.assertEqual(result.status, "output_limit")
        self.assertEqual(len(result.stdout) + len(result.stderr), 16 * 1024)

    def test_utf8_expansion_also_capped(self):
        result = collect(fixture("import os; os.write(1, b'\\xff'*8)"), b"", limit=8)
        self.assertEqual(result.status, "output_limit")
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 8)

    def test_timeout_with_blocked_input(self):
        process = fixture("import time; time.sleep(10)")
        result = collect(process, b"a" * (MAX_CODE + MAX_STDIN), seconds=0.2)
        self.assertEqual(result.status, "timed_out")
        self.assertIsNotNone(process.poll())


class SandboxTests(unittest.TestCase):
    def test_bootstrap_failure_returns_empty_infrastructure_result_and_cleans_up(self):
        docker = Mock(spec=Docker)
        docker.control.return_value = SimpleNamespace(returncode=0)
        docker.start.return_value = fixture("import sys; print('boot failed', file=sys.stderr)")
        sandbox = Sandbox(docker, {"python": PIN})
        self.assertEqual(sandbox.execute(Job("python", b"pass", b"")), Result("infrastructure_error"))
        docker.metadata.assert_not_called()
        docker.remove.assert_called_once_with(docker.start.call_args.args[0])

    def test_remove_called_when_create_fails(self):
        class FakeDocker:
            def control(self, *args, **kwargs):
                self.created_name = args[3]
                return SimpleNamespace(returncode=1)

            def remove(self, name):
                self.removed_name = name

        docker = FakeDocker()
        sandbox = Sandbox(docker, {"python": PIN})
        self.assertEqual(sandbox.execute(Job("python", b"print(3)", b"")), Result("infrastructure_error"))
        self.assertEqual(docker.created_name, docker.removed_name)

    def test_cleanup_failure_blocks_later_requests(self):
        class FakeDocker:
            creations = 0

            def control(self, *args, **kwargs):
                self.creations += 1
                return SimpleNamespace(returncode=1)

            def remove(self, name):
                raise InfrastructureError("cleanup fixture")

        docker = FakeDocker()
        sandbox = Sandbox(docker, {"python": PIN})
        job = Job("python", b"print(3)", b"")
        self.assertEqual(sandbox.execute(job), Result("infrastructure_error"))
        self.assertTrue(sandbox.unhealthy.is_set())
        self.assertEqual(sandbox.execute(job), Result("infrastructure_error"))
        self.assertEqual(docker.creations, 1)


class DockerHostInfoTests(unittest.TestCase):
    def host_info(self, wire):
        with patch("sandbox.socket") as transport:
            sock = transport.socket.return_value.__enter__.return_value
            sock.makefile.return_value = io.BytesIO(wire)
            info = Docker("docker", "unused").host_info(timeout=PREFLIGHT_SECONDS)
            transport.socket.assert_called_once_with(transport.AF_UNIX, transport.SOCK_STREAM)
            sock.settimeout.assert_called_once_with(PREFLIGHT_SECONDS)
            sock.connect.assert_called_once_with(DOCKER_SOCKET)
            self.assertTrue(sock.sendall.call_args.args[0].startswith(b"GET /v1.44/info HTTP/1.1\r\n"))
            return info

    def test_reads_daemon_json_over_local_socket(self):
        self.assertEqual(self.host_info(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
                                        b'b\r\n{"ok":true}\r\n0\r\n\r\n'), {"ok": True})

    def test_rejects_failed_truncated_invalid_or_oversized_responses(self):
        responses = (
            b"HTTP/1.1 503 Unavailable\r\n\r\n{}",
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n{}",
            b"HTTP/1.1 200 OK\r\n\r\ninvalid",
            b"HTTP/1.1 200 OK\r\nContent-Length: 2000000\r\n\r\n",
            b"HTTP/1.1 200 OK\r\n\r\n" + b" " * (MAX_HOST_INFO + 1),
        )
        for wire in responses:
            with self.subTest(prefix=wire[:42]), self.assertRaises(InfrastructureError):
                self.host_info(wire)


class DockerCleanupTests(unittest.TestCase):
    def test_force_removal_timeout_is_reconciled_by_ownership_check(self):
        docker = Docker("docker", "unused")
        listing = SimpleNamespace(returncode=0, stdout=(NAME + "\n").encode())
        empty = SimpleNamespace(returncode=0, stdout=b"")
        timeout = InfrastructureError("Docker control command timed out")
        with patch.object(docker, "control", side_effect=[listing, timeout, empty]) as control:
            docker.remove(NAME)

        initial, remove, verify = control.call_args_list
        self.assertEqual(initial.args, verify.args)
        self.assertIn(f"label={OWNER}", verify.args)
        self.assertIn(f"name=^/{NAME}$", verify.args)
        self.assertEqual(remove.args, ("container", "rm", "--force", "--volumes", NAME))
        self.assertEqual(initial.kwargs["timeout"], CLEANUP_CONTROL_SECONDS)
        self.assertGreater(remove.kwargs["timeout"], CLEANUP_CONTROL_SECONDS)
        self.assertGreater(verify.kwargs["timeout"], 0)
        self.assertLessEqual(verify.kwargs["timeout"], CLEANUP_CONTROL_SECONDS)

    def test_container_still_present_after_removal_timeout_fails_cleanup(self):
        docker = Docker("docker", "unused")
        listing = SimpleNamespace(returncode=0, stdout=(NAME + "\n").encode())
        timeout = InfrastructureError("Docker control command timed out")
        with patch.object(docker, "control", side_effect=[listing, timeout, listing]):
            with self.assertRaisesRegex(InfrastructureError, "Runner container survived cleanup"):
                docker.remove(NAME)


class TransportTests(unittest.TestCase):
    def setUp(self):
        sandbox = SimpleNamespace(execute=lambda job: Result("completed", job.stdin.decode()))
        self.server = Broker(("127.0.0.1", 0), AUTH, sandbox)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def request(self, path="/v1/execute", auth=AUTH, body=None, extra_headers=None):
        headers = {"Authorization": f"Bearer {auth}", "Content-Type": "application/json; charset=utf-8"}
        headers.update(extra_headers or {})
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request("POST", path, document() if body is None else body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_authenticated_contract_and_routing(self):
        self.assertEqual(self.request(), (200, {"status": "completed", "stdout": "مرحبا\n", "stderr": ""}))
        self.assertEqual(self.request(auth="wrong")[0], 401)
        self.assertEqual(self.request(path="/other")[0], 404)

    def test_body_bounds(self):
        self.assertEqual(self.request(body=b"", extra_headers={"Content-Length": str(MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.request(extra_headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(self.request(body=document(code="a" * (MAX_CODE + 1)))[0], 400)
        self.assertEqual(self.request(extra_headers={"Content-Type": "text/plain"})[0], 415)

    def test_parallel_job_limit(self):
        for _ in range(2):
            self.assertTrue(self.server.jobs.acquire(blocking=False))
        self.assertEqual(self.request(), (503, {"error": "runner_busy"}))


if __name__ == "__main__":
    unittest.main()
