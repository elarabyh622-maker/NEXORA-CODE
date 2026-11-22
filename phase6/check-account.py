"""Check account and commercial journeys on a fresh loopback PostgreSQL cluster."""

import argparse
import hashlib
from pathlib import Path
import runpy
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
release = runpy.run_path(str(ROOT / "phase18/check-release.py"))
fixture = release["fixture"]
Client, call, require = fixture.Client, fixture.call, fixture.require
CANCEL = "/me/access-cancellation"
QUEUE = "/admin/access/cancellations"
BUY = "/me/purchases"
ORDERS = "/admin/purchases"


def known_account(origin, name):
    client, password = Client(origin), secrets.token_urlsafe(25)
    client.refresh_csrf()
    call(client, "POST", "/auth/register", {
        "userName": name, "displayName": name, "password": password}, status=201)
    client.refresh_csrf()
    return client, password


def login(origin, name, password, status=200):
    client = Client(origin)
    client.refresh_csrf()
    call(client, "POST", "/auth/login", {"userName": name, "password": password}, status=status)
    if status == 200:
        client.refresh_csrf()
    return client


def without_csrf(client, path, body=None):
    status, result, _ = fixture.checks.request_after_rate_limit(
        lambda: client.request("POST", "/api/v1" + path, body, csrf=False))
    require(status == 400 and result["code"] == "csrf_invalid", f"Missing CSRF on {path}")


def check_password(origin, admin, admin_password):
    name = "account_security_learner"
    learner, password = known_account(origin, name)
    other = login(origin, name, password)
    change = "/auth/change-password"
    issue = "/auth/recovery-code"
    reset = "/auth/reset-password"
    assist = "/admin/accounts/recovery-code"
    new_password = secrets.token_urlsafe(25)
    body = {"currentPassword": password, "newPassword": new_password}
    without_csrf(learner, change, body)
    call(learner, "POST", change, {**body, "currentPassword": "incorrect"}, status=400)
    call(learner, "POST", change, body, status=204)
    for stale in (learner, other):
        call(stale, "GET", "/auth/me", status=401)
    login(origin, name, password, status=401)
    learner = login(origin, name, new_password)
    anon = Client(origin)
    anon.refresh_csrf()
    call(anon, "POST", issue, {"currentPassword": password}, status=401)
    call(learner, "POST", assist, {"userName": name, "currentPassword": new_password}, status=403)
    code = call(learner, "POST", issue, {"currentPassword": new_password})["recoveryCode"]
    recovered_password = secrets.token_urlsafe(25)
    recovery = {"userName": name, "newPassword": recovered_password, "recoveryCode": code}
    without_csrf(anon, reset, recovery)
    call(anon, "POST", reset, recovery, status=204)
    call(learner, "GET", "/auth/me", status=401)
    call(anon, "GET", "/auth/me", status=401)
    call(anon, "POST", reset, recovery, status=400)
    recovered = login(origin, name, recovered_password)
    assisted = {"userName": name, "currentPassword": admin_password}
    call(admin, "POST", assist, {**assisted, "currentPassword": "incorrect"}, status=400)
    call(admin, "POST", assist, {**assisted, "userName": "account_fixture_admin"}, status=404)
    assistance = call(admin, "POST", assist, assisted)
    require(bool(assistance["expiresAt"]), "Admin recovery code has an expiry")
    final_password = secrets.token_urlsafe(25)
    call(anon, "POST", reset, {**recovery, "newPassword": final_password,
                                "recoveryCode": assistance["recoveryCode"]}, status=204)
    call(recovered, "GET", "/auth/me", status=401)
    login(origin, name, final_password)
    print("PASSED: password change, session revocation, one-time recovery and admin-assisted recovery", flush=True)


def check_cancellations(admin, learner, name, stranger, sql):
    def grant(**scope):
        call(admin, "POST", "/admin/access/grant", {"userName": name, **scope})

    def submit():
        return call(learner, "POST", CANCEL)["request"]

    def resolve(entry, approve, status=204):
        call(admin, "POST", f"{QUEUE}/{entry['id']}/resolve", {"approve": approve}, status=status)

    require(call(learner, "GET", CANCEL)["request"] is None, "Initial cancellation is empty")
    call(learner, "POST", CANCEL, status=403)
    call(learner, "GET", QUEUE, status=403)
    grant(goalId="go")
    grant(lessonId="java-project-01")
    grant()
    plan = call(learner, "POST", "/learning-plans", {"releaseId": release["NEW"], "goalId": "go"}, status=201)
    without_csrf(learner, CANCEL)
    first = submit()
    require(first["status"] == "pending" and first == submit(), "Repeated cancellation returns same pending request")
    require(call(learner, "GET", "/me/access")["active"], "Pending cancellation preserves access")
    require(call(stranger, "GET", CANCEL)["request"] is None, "Cancellation is private to the requesting learner")
    rows = call(admin, "GET", QUEUE)
    require([(r["id"], r["userName"]) for r in rows] == [(first["id"], name)], "Pending admin queue")
    without_csrf(admin, f"{QUEUE}/{first['id']}/resolve", {"approve": True})
    resolve(first, False)
    resolve(first, False)
    resolve(first, True, 409)
    require(call(learner, "GET", CANCEL)["request"]["status"] == "declined", "Learner sees declined decision")
    require(call(learner, "GET", "/me/access")["active"], "Decline preserves access")
    second = submit()
    require(first["id"] != second["id"], "Separate request after decline")
    resolve(second, True)
    require(not call(learner, "GET", "/me/access")["active"], "Approval removes full and scoped access")
    require(call(learner, "GET", CANCEL)["request"]["status"] == "approved", "Approved status visible after access ends")
    require(call(admin, "GET", QUEUE) == [], "Resolved queue is empty")
    grant(goalId="go")
    resolve(second, True)
    require(call(learner, "GET", "/me/access")["goalIds"] == ["go"], "Resolve retry preserves later grants")
    require(call(learner, "GET", "/me/plan")["id"] == plan["id"], "Cancellation preserves prior plan")
    require(int(sql("SELECT count(*) FROM public.audit WHERE action='access.cancellation.approve'")) == 1,
            "Only one approval audit")
    print("PASSED: authenticated cancellation, pending access, decisions, idempotency and saved plan", flush=True)


def check_purchases(admin, buyer, other, sql):
    goal = "go"
    buy = {"goalId": goal}
    price = "/admin/access/offers/" + goal
    call(buyer, "GET", ORDERS, status=403)
    call(buyer, "POST", BUY, buy, status=404)
    call(admin, "PUT", price, {"price": 120, "currency": "EGP"})
    without_csrf(buyer, BUY, buy)
    first = call(buyer, "POST", BUY, buy)
    require(first["status"] == "pending" and first["checkoutUrl"] is None, "New order awaits a link")
    call(admin, "PUT", price, {"price": 155, "currency": "EGP"})
    require(call(buyer, "POST", BUY, buy) == first and first["price"] == 120,
            "One open order with unchanged price snapshot")
    require(call(other, "GET", BUY) == [], "Buyer order history is private")
    route = f"{ORDERS}/{first['id']}"
    call(buyer, "POST", route + "/close", status=403)
    without_csrf(admin, route + "/close")
    call(admin, "POST", route + "/close", status=204)
    call(admin, "POST", route + "/close", status=204)
    require(call(buyer, "GET", BUY)[0]["status"] == "closed", "Closed order visible to buyer")
    second = call(buyer, "POST", BUY, buy)
    require(second["id"] != first["id"] and second["price"] == 155 and second["currency"] == "EGP",
            "New order uses the updated offer")
    route = f"{ORDERS}/{second['id']}"
    link = {"checkoutUrl": "https://paymob.link/FixtureRef001"}
    reference = {"paymentReference": "123456789"}
    call(admin, "POST", route + "/confirm", reference, status=409)
    call(admin, "PUT", route + "/link", {"checkoutUrl": "https://example.invalid/fixture"}, status=400)
    call(admin, "PUT", route + "/link", link, status=204)
    call(admin, "PUT", route + "/link", link, status=204)
    visible = next(r for r in call(buyer, "GET", BUY) if r["id"] == second["id"])
    require(visible["status"] == "link-ready" and visible["checkoutUrl"] == link["checkoutUrl"],
            "Ready link visible to the buyer")
    require(not call(buyer, "GET", "/me/access")["active"], "Publishing a link grants no entitlement")
    call(admin, "POST", route + "/close", status=409)
    call(admin, "POST", route + "/confirm", {"paymentReference": "not-numeric"}, status=400)
    call(admin, "POST", route + "/confirm", reference, status=204)
    require(call(buyer, "GET", "/me/access")["goalIds"] == [goal], "Confirmation grants only the purchased goal")
    call(buyer, "POST", BUY, buy, status=409)
    history = next(r for r in call(buyer, "GET", BUY) if r["id"] == second["id"])
    require(history["status"] == "confirmed" and history.get("checkoutUrl") is None, "Closed checkout link hidden")
    require(not call(admin, "GET", ORDERS), "Completed orders leave the admin queue")
    before = sql("SELECT count(*) FROM public.audit")
    call(admin, "POST", route + "/confirm", reference, status=204)
    require(before == sql("SELECT count(*) FROM public.audit"), "Confirm retry adds no audit")
    call(admin, "POST", route + "/confirm", {"paymentReference": "999999"}, status=409)
    call(admin, "POST", "/admin/access/revoke", {"userName": "account_fixture_buyer", "goalId": goal})
    call(admin, "POST", route + "/confirm", reference, status=204)
    require(not call(buyer, "GET", "/me/access")["active"], "Confirm retry never regrants revoked content")
    # Another real order must not reuse the first payment or its checkout link.
    call(admin, "PUT", "/admin/access/offers/python", {"price": 155, "currency": "EGP"})
    third = call(other, "POST", BUY, {"goalId": "python"})
    other_route = f"{ORDERS}/{third['id']}"
    call(admin, "PUT", other_route + "/link", link, status=409)
    expired_link = {"checkoutUrl": "https://paymob.link/FixtureRef002"}
    call(admin, "PUT", other_route + "/link", expired_link, status=204)
    call(admin, "POST", other_route + "/confirm", reference, status=409)
    close = other_route + "/close"
    call(admin, "POST", close, status=409)
    call(admin, "POST", close, {"confirmedUnpaidAndDisabled": False}, status=409)
    still_open = next(r for r in call(other, "GET", BUY) if r["id"] == third["id"])
    require(still_open["status"] == "link-ready" and still_open["checkoutUrl"] == expired_link["checkoutUrl"],
            "Unconfirmed closure preserves the active order and its link")
    verified = {"confirmedUnpaidAndDisabled": True}
    call(admin, "POST", close, verified, status=204)
    audit_after_close = sql("SELECT count(*) FROM public.audit")
    call(admin, "POST", close, verified, status=204)
    require(audit_after_close == sql("SELECT count(*) FROM public.audit"), "Repeated verified closure adds no audit")
    closed = next(r for r in call(other, "GET", BUY) if r["id"] == third["id"])
    require(closed["status"] == "closed" and closed.get("checkoutUrl") is None, "Closed history hides expired link")
    fresh = call(other, "POST", BUY, {"goalId": "python"})
    require(fresh["id"] != third["id"] and fresh["status"] == "pending", "Fresh order after expired link")
    call(admin, "PUT", f"{ORDERS}/{fresh['id']}/link", expired_link, status=409)
    call(other, "GET", "/content/" + release["NEW"] + "/lessons/py-02", status=403)
    print("PASSED: private purchase requests, price snapshot, hosted link publication and unique confirmation", flush=True)


def journey(origin, command, publish, sql):
    publish()
    guest = Client(origin)
    guest.refresh_csrf()
    require(call(guest, "GET", "/catalog")["activeReleaseId"] == release["NEW"], "Exact Phase 18 is active")
    for path in (CANCEL, QUEUE, BUY, ORDERS):
        call(guest, "GET", path, status=401)
    # Match deployment grants on migrated databases, including the private migration ledger.
    sql("REVOKE ALL ON public.masar_schema_migrations FROM qa_app")
    require(sql("SELECT has_table_privilege('qa_app','public.masar_schema_migrations','SELECT')").strip() == b"f",
            "Runtime has no access to the migration ledger")
    admin, admin_password = known_account(origin, "account_fixture_admin")
    command("--promote-admin", "account_fixture_admin")
    admin.refresh_csrf()
    learner_name = "account_fixture_learner"
    learner, _ = known_account(origin, learner_name)
    buyer, _ = known_account(origin, "account_fixture_buyer")
    check_cancellations(admin, learner, learner_name, buyer, sql)
    check_purchases(admin, buyer, learner, sql)
    check_password(origin, admin, admin_password)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=ROOT / "phase18/dist/curriculum.json")
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--browser-wwwroot", type=Path,
                        help="Also verify the staged frontend in Edge using the disposable API")
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    require(digest == args.bundle_sha256.lower(), "Bundle differs from reviewed SHA-256")
    fixture.PREVIOUS = release["PREDECESSORS"]
    fixture.ZIP_NAME = release["ZIP_NAME"]
    def staged_journey(origin, command, publish, sql):
        journey(origin, command, publish, sql)
        if args.browser_wwwroot:
            subprocess.run(["node", str(ROOT / "phase6/.local/check-account-browser.cjs"),
                            "--fixture", origin + "/", str(args.browser_wwwroot.resolve(strict=True))],
                           timeout=150, check=True)

    fixture.check_journey = staged_journey
    fixture.run_isolated(args.assembly.resolve(strict=True), args.postgres_bin.absolute(), bundle, digest)


if __name__ == "__main__":
    main()
