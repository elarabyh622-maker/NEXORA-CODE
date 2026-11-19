import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient

from catalogue import auth, store
from catalogue.app import create_app


PRODUCT = {"name": "دفتر", "category": "قرطاسية", "price_minor": 1250, "stock": 3}


@pytest.fixture
def site(tmp_path):
    path = tmp_path / "catalogue.sqlite3"
    with TestClient(create_app(path)) as client:
        yield client, path


def sign_in(site, role="admin"):
    client, path = site
    password = secrets.token_urlsafe(20)
    auth.create_user(path, role, password, role)
    result = client.post("/api/login", json={"username": role, "password": password})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    token = result.json()["access_token"]
    return {"Authorization": "Bearer " + token}


def test_home_docs_and_empty_catalogue(site):
    client, _ = site
    assert 'dir="rtl"' in client.get("/").text
    assert client.get("/app.js").status_code == client.get("/style.css").status_code == 200
    assert client.get("/docs").status_code == 200
    assert "/api/products" in client.get("/openapi.json").json()["paths"]
    assert client.get("/api/products").json() == []


def test_crud_and_restart(site):
    client, path = site
    headers = sign_in(site)
    response = client.post("/api/products", headers=headers, json=PRODUCT)
    assert response.status_code == 201
    product = response.json()
    assert product == {**PRODUCT, "id": product["id"]}
    url = "/api/products/" + str(product["id"])
    assert client.get(url).json() == product
    changed = {**PRODUCT, "price_minor": 1550, "stock": 0}
    assert client.put(url, headers=headers, json=changed).json() == {**changed, "id": product["id"]}
    with TestClient(create_app(path)) as restarted:
        assert restarted.get(url).json()["stock"] == 0
        assert restarted.get("/api/me", headers=headers).json() == {"username": "admin", "role": "admin"}
    deleted = client.delete(url, headers=headers)
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get(url).status_code == 404
    assert client.put(url, headers=headers, json=changed).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404


def test_filter_binds_user_text(site):
    client, path = site
    with store.transaction(path) as db:
        p = store.add_product(db, **PRODUCT)
        store.add_product(db, "دفتر O'Brien 50%", "هدايا", 250, 8)
    assert client.get("/api/products", params={"q": " دف ", "category": "قرطاسية"}).json() == [p]
    assert [r["category"] for r in client.get("/api/products", params={"q": "O'Brien 50%"}).json()] == ["هدايا"]
    assert client.get("/api/products", params={"q": "ممحاة"}).json() == []


def test_product_validation(site):
    client, _ = site
    headers = sign_in(site)
    for invalid in ({"name": " "}, {"category": ""}, {"stock": -1}, {"stock": True},
                    {"name": "\x00دفتر"}, {"name": "دف\x00تر"},
                    {"category": "\x00قرطاسية"}, {"category": "قرطا\x00سية"},
                    {"price_minor": 2.5}, {"stock": "1"}, {"role": "admin"}):
        response = client.post("/api/products", json={**PRODUCT, **invalid}, headers=headers)
        assert response.status_code == 422, invalid
    assert client.get("/api/products").json() == []
    assert client.get("/api/products/" + str(2**64)).status_code == 422


def test_writes_require_admin(site):
    client, _ = site
    headers = sign_in(site, "reader")
    assert client.get("/api/me", headers=headers).json()["role"] == "reader"
    for method, url, body in (("POST", "/api/products", PRODUCT), ("PUT", "/api/products/1", PRODUCT),
                              ("DELETE", "/api/products/1", None)):
        assert client.request(method, url, json=body).status_code == 401
        assert client.request(method, url, json=body, headers=headers).status_code == 403
    assert client.get("/api/products").json() == []


def test_session_role_expiry_and_logout(site):
    client, path = site
    headers = sign_in(site)
    with store.transaction(path) as db:
        saved = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        assert saved == auth.token_hash(headers["Authorization"].split()[1])
        db.execute("UPDATE users SET role = 'reader' WHERE username = 'admin'")
    assert client.post("/api/products", json=PRODUCT, headers=headers).status_code == 403
    with store.transaction(path) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    assert client.get("/api/me", headers=headers).status_code == 401
    headers = sign_in(site, "reader")
    assert client.post("/api/logout", headers=headers).status_code == 204
    assert client.get("/api/me", headers=headers).status_code == 401


def test_login_errors_and_throttle(site):
    client, path = site
    password = secrets.token_urlsafe(20)
    auth.create_user(path, "local", password, "reader")
    wrong = {"username": "local", "password": "incorrect"}
    unknown = {**wrong, "username": "unknown"}
    r1 = client.post("/api/login", json=wrong)
    r2 = client.post("/api/login", json=unknown)
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()
    response = client.post("/api/login", json={**wrong, "role": "admin", "password": password})
    assert response.status_code == 422 and password not in response.text
    for _ in range(6):
        assert client.post("/api/login", json=wrong).status_code == 401
    throttled = client.post("/api/login", json=wrong)
    assert throttled.status_code == 429 and throttled.headers["retry-after"] == "60"


def test_atomic_rollback(site):
    _, path = site
    with pytest.raises(sqlite3.IntegrityError), store.transaction(path) as db:
        store.add_product(db, **PRODUCT)
        store.add_product(db, "قلم", "قرطاسية", 20, -1)
    with store.transaction(path) as db:
        assert store.list_products(db) == []


def test_password_salts():
    password = secrets.token_urlsafe(20)
    first, second = auth.hash_password(password), auth.hash_password(password)
    assert first != second and password not in first
    assert auth.verify_password(password, first)
    assert not auth.verify_password(password + "x", first)
