import hashlib
import hmac
import secrets
import time

from .store import transaction


def derive_password(password, salt):
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=3,
        maxmem=64 * 1024 * 1024, dklen=32,
    )


def hash_password(password):
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}:{derive_password(password, salt).hex()}"


def verify_password(password, stored_hash):
    salt, expected = stored_hash.split(":")
    actual = derive_password(password, bytes.fromhex(salt))
    return hmac.compare_digest(actual, bytes.fromhex(expected))


def create_user(db_path, username, password, role):
    username = username.strip()
    if not 1 <= len(username) <= 64 or not 12 <= len(password) <= 128:
        raise ValueError("اكتب اسمًا بين 1 و64 حرفًا وكلمة مرور بين 12 و128 حرفًا.")
    if role not in ("admin", "reader"):
        raise ValueError("اختر دور admin أو reader.")
    password_hash = hash_password(password)
    with transaction(db_path) as db:
        db.execute(
            "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(db, user_id):
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    db.execute(
        "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (token_hash(token), user_id, now + 3600),
    )
    return token


def session_user(db, token):
    return db.execute("""
        SELECT users.username, users.role FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ? AND sessions.expires_at > ?
    """, (token_hash(token), int(time.time()))).fetchone()
