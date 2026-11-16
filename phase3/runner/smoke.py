"""Run the console contract smoke suite against a provisioned runner."""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8787/v1/execute")
    options = parser.parse_args()
    url = urllib.parse.urlsplit(options.url)
    if url.scheme != "https" and (url.scheme != "http" or url.hostname != "127.0.0.1"):
        parser.error("Use HTTPS for a remote runner or HTTP on 127.0.0.1")
    token = os.environ["NEXORA_RUNNER_BEARER_TOKEN"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def execute(language, code, stdin="", authorization=token):
        request = urllib.request.Request(
            options.url,
            data=json.dumps({"language": language, "code": code, "stdin": stdin}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {authorization}"},
        )
        with opener.open(request, timeout=25) as response:
            return json.load(response)

    def check(label, expected, language, code, stdin="", stdout=None):
        result = execute(language, code, stdin)
        if result["status"] != expected or (stdout is not None and result["stdout"] != stdout):
            raise SystemExit(f"FAIL {label} (received {result['status']})")
        size = len(result["stdout"].encode()) + len(result["stderr"].encode())
        if size > 16 * 1024:
            raise SystemExit(f"FAIL {label} (received {size} bytes)")
        print(f"PASS {label}")

    try:
        execute("python", "print(1)", authorization="invalid")
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
        print("PASS unauthorized request")
    else:
        raise SystemExit("FAIL unauthorized request was accepted")

    check("Python and Unicode stdin", "completed", "python", "print(input().strip())", "مرحبا\n", "مرحبا\n")
    check("Node CommonJS and stdin EOF", "completed", "javascript",
          "console.log(require('node:fs').readFileSync(0, 'utf8').trim())", "مرحبا\n", "مرحبا\n")
    check("Code error", "code_error", "python", "print(1 / 0)")
    check("Output cap", "output_limit", "javascript", "console.log('x'.repeat(20000))")
    check("Wall deadline", "timed_out", "python", "import time\ntime.sleep(60)")


if __name__ == "__main__":
    main()
