"""Paid plans and single lessons on the isolated commercial HTTPS backend."""

from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
import argparse
import runpy
import secrets
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase2" / "scripts"))
from http_integration import Client, expect, require


BASE = "http://127.0.0.1:5199/nexora-commercial"
MOUNT = "/nexora-commercial"
API = "/api/v1"
RELEASE = "phase7-ar-v1"
CONTENT = f"{API}/content/{RELEASE}"
ADMIN = f"{API}/admin/access"
ZIP = "/projects/web-starter-v1.zip"


class ProxyClient(Client):
    def __init__(self, authority):
        super().__init__(BASE)
        # The client remains on loopback and simulates the HTTP hop from the TLS proxy.
        self.cookies = CookieJar(DefaultCookiePolicy(secure_protocols=("https", "http")))
        class ProxyHeaders(urllib.request.BaseHandler):
            handler_order = 100

            def http_request(self, request):
                require(request.host == "127.0.0.1:5199", "fixture HTTP hop must stay on loopback")
                request.add_header("Host", authority)
                request.add_header("X-Forwarded-Proto", "https")
                request.add_header("X-Forwarded-For", "127.0.0.1")
                return request

        self.opener = urllib.request.build_opener(ProxyHeaders(), urllib.request.HTTPCookieProcessor(self.cookies))


def call(client, method, path, expected=200, body=None):
    status, payload, _ = client.request(method, path, body)
    expect(status, expected, path)
    return payload


def account(authority, kind):
    user = ProxyClient(authority)
    name = "launch_qa_" + kind + "_" + secrets.token_hex(6)
    user.refresh_csrf()
    call(user, "POST", f"{API}/auth/register", 201, {
        "userName": name, "displayName": "حساب اختبار الإطلاق", "password": secrets.token_urlsafe(24),
    })
    user.refresh_csrf()
    require(any(c.name == "Masar.CommercialTest.Session" and c.secure and c.path == MOUNT for c in user.cookies),
            "isolated secure session cookie")
    return user, name


def suite(authority, assembly):
    guard = runpy.run_path(str(Path(__file__).with_name("check-commercial.py")))["require_test_database"]
    guard("ConnectionStrings__Masar", "masar_app")
    guard("ConnectionStrings__Migration", "masar_bootstrap")
    guest = ProxyClient(authority)
    catalog = call(guest, "GET", f"{API}/catalog")
    require(catalog["accessRequired"] and catalog["activeReleaseId"] == RELEASE, "isolated commercial release")
    guest.refresh_csrf()
    require(any(c.name == "Masar.CommercialTest.Csrf" and c.secure and c.path == MOUNT for c in guest.cookies),
            "isolated secure CSRF cookie")
    call(guest, "GET", CONTENT, 401)
    learner, learner_name = account(authority, "learner")
    admin, admin_name = account(authority, "admin")
    promotion = subprocess.run(["dotnet", str(assembly), "--promote-admin", admin_name], cwd=assembly.parent,
                               check=False, capture_output=True, timeout=20)
    require(promotion.returncode == 0, "fixture administrator promotion")
    admin.refresh_csrf()
    call(learner, "GET", CONTENT, 403)
    call(learner, "GET", f"{ADMIN}/offers", 403)
    targets = call(admin, "GET", f"{ADMIN}/targets")
    require(any(item["id"] == "python" for item in targets["goals"]), "Python administrative target")
    require(any(item["id"] == "web-12" for item in targets["lessons"]), "individual lesson administrative target")
    rows = call(admin, "GET", f"{ADMIN}/accounts?query={learner_name}")
    require(any(row["userName"] == learner_name for row in rows), "learner search")
    original_prices = {offer["goalId"]: offer for offer in catalog["offers"]}

    def access(action, **scope):
        return call(admin, "POST", f"{ADMIN}/{action}", body={"userName": learner_name, **scope})

    try:
        for goal, price in (("python", 125), ("web", 240)):
            call(admin, "PUT", f"{ADMIN}/offers/{goal}", body={"price": price, "currency": "EGP"})
        offers = {offer["goalId"]: offer for offer in call(guest, "GET", f"{API}/catalog")["offers"]}
        require(offers["python"]["price"] == 125 and offers["web"]["price"] == 240, "independent advertised prices")
        call(learner, "GET", CONTENT, 403)
        access("grant", goalId="python")
        projected = call(learner, "GET", CONTENT)["sample"]
        expected = {f"{prefix}-{i:02}" for prefix in ("core", "py") for i in range(1, 13)}
        require({lesson["id"] for lesson in projected["lessons"]} == expected, "purchased plan and prerequisites only")
        call(learner, "GET", f"{CONTENT}/lessons/core-07")
        call(learner, "GET", f"{CONTENT}/lessons/py-02")
        call(learner, "GET", f"{CONTENT}/lessons/web-12", 403)
        call(learner, "GET", f"{API}/lab/exercises/{RELEASE}/web-12", 403)
        call(learner, "GET", f"{API}/lab/exercises/{RELEASE}/py-02")
        call(learner, "GET", ZIP, 403)
        preview = lambda goal: {"releaseId": RELEASE, "goalId": goal}
        call(learner, "POST", f"{API}/plan-previews", 403, preview("web"))
        plan = call(learner, "POST", f"{API}/learning-plans", 201, preview("python"))
        call(learner, "PUT", f"{API}/lab/drafts/{RELEASE}/py-02-lab", body={"code": "print(6)", "expectedVersion": 0})
        access("grant", lessonId="web-12")
        call(learner, "GET", f"{CONTENT}/lessons/web-12")
        call(learner, "GET", f"{CONTENT}/lessons/web-11", 403)
        call(learner, "POST", f"{API}/plan-previews", 403, preview("web"))
        call(learner, "HEAD", ZIP)
        access("revoke", goalId="python")
        require(call(learner, "GET", f"{API}/me/access")["active"], "the independent lesson stays open")
        call(learner, "GET", f"{CONTENT}/lessons/py-02", 403)
        call(learner, "GET", f"{API}/learning-plans/{plan['id']}", 403)
        call(learner, "GET", f"{API}/lab/drafts/{RELEASE}/py-02-lab", 403)
        access("grant", goalId="web")
        next_plan = call(learner, "POST", f"{API}/learning-plans", 201, preview("web"))
        require(next_plan["revision"] == plan["revision"] + 1, "revocation preserves global plan revisions")
        access("revoke", goalId="web")
        access("revoke", lessonId="web-12")
        call(learner, "GET", CONTENT, 403)
        print("PASSED: independent prices, scoped lessons/ZIP/plans/labs, revocation and secure cookies.", flush=True)
    finally:
        for goal in ("python", "web"):
            access("revoke", goalId=goal)
            old = original_prices.get(goal, {"price": None, "currency": None})
            call(admin, "PUT", f"{ADMIN}/offers/{goal}", body={"price": old["price"], "currency": old["currency"]})
        access("revoke", lessonId="web-12")


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("authority")
    args.add_argument("assembly", type=Path)
    options = args.parse_args()
    suite(options.authority, options.assembly.resolve(strict=True))
