"""Verify generated curriculum cases through the configured gVisor broker."""

import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit


CHECKS = Path(__file__).resolve().parent / ".local" / "execution-checks.json"
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))
MAX_RESPONSE_BYTES = 112 * 1024
MAX_OUTPUT_BYTES = 16 * 1024
TIMEOUT_SECONDS = 25
STATUS_FAILURES = {"timed_out", "output_limit", "code_error"}


def load_cases():
    cases = json.loads(CHECKS.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Build the curriculum before running execution checks.")
    labels = set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or any(not isinstance(case.get(field), str) for field in ("label", "language", "code", "input", "output"))
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)* (?:example|case) [1-9][0-9]*", case["label"])
            or case["language"] not in {"python", "javascript"}
            or case["label"] in labels
        ):
            raise ValueError("The generated execution manifest has an invalid case.")
        labels.add(case["label"])
    return cases


def runner_config():
    raw_url = os.environ.get("MASAR_CODE_LAB_RUNNER_URL", "")
    token = os.environ.get("MASAR_CODE_LAB_RUNNER_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise ValueError("Set a valid MASAR_CODE_LAB_RUNNER_TOKEN.")

    if any(character.isspace() or ord(character) < 32 for character in raw_url) or any(
        character in raw_url for character in "?#"
    ):
        raise ValueError("Set MASAR_CODE_LAB_RUNNER_URL to an HTTP or HTTPS origin.")
    try:
        url = urlsplit(raw_url)
        host = url.hostname
        port = url.port
    except ValueError:
        raise ValueError("Set MASAR_CODE_LAB_RUNNER_URL to an HTTP or HTTPS origin.") from None
    if url.scheme not in {"http", "https"} or not host or port == 0 or url.path not in {"", "/"} or url.username is not None:
        raise ValueError("Set MASAR_CODE_LAB_RUNNER_URL to an HTTP or HTTPS origin.")

    tls = ssl.create_default_context() if url.scheme == "https" else None
    port = port or (443 if tls else 80)
    if tls is None:
        try:
            loopback_host = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback_host = host == "localhost"
        if not loopback_host:
            raise ValueError("The runner requires loopback HTTP or private HTTPS.")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("The configured runner origin did not resolve.") from None
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_loopback and (tls is None or not any(ip in network for network in PRIVATE_NETWORKS)):
            raise ValueError("The runner requires loopback HTTP or private HTTPS.")
    return host, port, addresses, tls, token


def connect(addresses, tls, host):
    # Use the checked IP for transport and the original hostname for certificate verification.
    for family, socket_type, protocol, _, address in addresses:
        peer = socket.socket(family, socket_type, protocol)
        try:
            peer.settimeout(TIMEOUT_SECONDS)
            peer.connect(address)
        except OSError:
            peer.close()
            continue
        if tls is None:
            return peer
        try:
            return tls.wrap_socket(peer, server_hostname=host)
        except OSError:
            peer.close()
            raise
    return None


def normalize_output(value):
    return value.replace("\r\n", "\n").removesuffix("\n")


def execute(config, case):
    host, port, addresses, tls, token = config
    connection = (http.client.HTTPSConnection if tls else http.client.HTTPConnection)(host, port)
    try:
        try:
            connection.sock = connect(addresses, tls, host)
        except OSError:
            return "blocked", "runner TLS handshake failed"
        if connection.sock is None:
            return "retry", "could not connect to the runner"

        payload = json.dumps({
            "language": case["language"], "code": case["code"], "stdin": case["input"],
        }, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            connection.request("POST", "/v1/execute", body=payload, headers=headers)
            with connection.getresponse() as response:
                if response.status in {429, 503}:
                    return "retry", f"runner unavailable (HTTP {response.status})"
                if response.status != 200:
                    return "blocked", f"runner rejected the request (HTTP {response.status})"
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, http.client.HTTPException):
            # The broker may still be processing this case after an interrupted response.
            return "blocked", "runner response was interrupted"

        if len(body) > MAX_RESPONSE_BYTES:
            return "blocked", "runner response exceeded the byte limit"
        try:
            result = json.loads(body.decode("utf-8"))
            status, stdout, stderr = (result[field] for field in ("status", "stdout", "stderr"))
            output_bytes = len(stdout.encode("utf-8")) + len(stderr.encode("utf-8"))
        except (ValueError, RecursionError, KeyError, TypeError, AttributeError):
            return "blocked", "runner response was invalid"
        if not isinstance(status, str) or output_bytes > MAX_OUTPUT_BYTES:
            return "blocked", "runner response was invalid"
        if status == "infrastructure_error":
            return "retry", "runner reported an infrastructure error"
        if status in STATUS_FAILURES:
            return "fail", f"expected completed status, got {status}"
        if status != "completed":
            return "blocked", "runner returned an unknown status"
        if normalize_output(stdout) != normalize_output(case["output"]):
            return "fail", "stdout differed from the expected output"
        return "pass", ""
    finally:
        connection.close()


def main():
    try:
        cases = load_cases()
    except (OSError, ValueError, RecursionError):
        print("BLOCKED: execution manifest is missing or invalid. Build the curriculum first.", file=sys.stderr)
        return 1
    try:
        config = runner_config()
    except ValueError as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 1

    passed = failed = blocked = retried = 0
    for index, case in enumerate(cases, 1):
        outcome, reason = execute(config, case)
        if outcome == "retry":
            retried += 1
            time.sleep(1)
            outcome, reason = execute(config, case)
        if outcome == "pass":
            passed += 1
            continue
        label = case["label"].replace(config[-1], "[redacted]")
        if outcome == "fail":
            failed += 1
            print(f"FAIL {label}: {reason}", file=sys.stderr)
        else:
            blocked += 1
            print(f"BLOCKED {label}: {reason}", file=sys.stderr)
        if outcome == "blocked":
            break
    skipped = len(cases) - index
    print(f"gVisor execution checks: {passed} passed, {failed} failed, "
          f"{blocked} blocked, {skipped} skipped, {retried} retried.")
    return int(failed + blocked + skipped != 0)


if __name__ == "__main__":
    sys.exit(main())

