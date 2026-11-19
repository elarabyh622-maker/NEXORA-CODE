import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


def database_path():
    return Path(os.environ.get("CATALOGUE_DB", "data/catalogue.sqlite3"))


@contextmanager
def transaction(db_path):
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        with db:  # commit بعد النجاح، rollback عند حدوث استثناء
            yield db


def initialize(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with transaction(db_path) as db:
        db.executescript("""
            BEGIN;
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 100),
                category TEXT NOT NULL CHECK(length(trim(category)) BETWEEN 1 AND 60),
                price_minor INTEGER NOT NULL CHECK(price_minor BETWEEN 0 AND 100000000),
                stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND 1000000)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('reader', 'admin'))
            ) STRICT;
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            ) STRICT;
        """)


def list_products(db, q="", category=""):
    # TODO 1: أضف البحث بجزء من الاسم والتطابق مع التصنيف عندما يُرسله المستخدم.
    # استخدم معاملات مربوطة، واحتفظ بترتيب النتائج عندما يكون البحث فارغًا.
    rows = db.execute("SELECT * FROM products ORDER BY id")
    return [dict(row) for row in rows]


def get_product(db, product_id):
    row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def add_product(db, name, category, price_minor, stock):
    cursor = db.execute(
        "INSERT INTO products(name, category, price_minor, stock) VALUES (?, ?, ?, ?)",
        (name, category, price_minor, stock),
    )
    return get_product(db, cursor.lastrowid)


def update_product(db, product_id, name, category, price_minor, stock):
    # TODO 2: حدّث المنتج المحدد بالمعرّف وأعد الصف بعد تعديله.
    # أعد None إذا لم يطابق التعديل أي صف، واترك إنهاء المعاملة للمتصل.
    return None


def delete_product(db, product_id):
    cursor = db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    return cursor.rowcount == 1
