import argparse
import getpass
import sqlite3

import uvicorn

from . import auth, store
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="كتالوج المنتجات المحلي")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("serve", help="تشغيل الكتالوج على 127.0.0.1:8000")
    add = commands.add_parser("create-user", help="إنشاء حساب على هذا الجهاز")
    add.add_argument("username")
    add.add_argument("--role", choices=("reader", "admin"), default="reader")
    args = parser.parse_args()
    if args.action == "serve":
        uvicorn.run(create_app(), host="127.0.0.1", port=8000)
        return
    password = getpass.getpass("كلمة المرور (12 حرفًا على الأقل): ")
    if password != getpass.getpass("أعد إدخال كلمة المرور: "):
        parser.exit(1, "كلمتا المرور غير متطابقتين.\n")
    path = store.database_path()
    store.initialize(path)
    try:
        auth.create_user(path, args.username, password, args.role)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except sqlite3.IntegrityError:
        parser.exit(1, "اسم الحساب مستخدم بالفعل.\n")
    print("تم إنشاء الحساب.")


if __name__ == "__main__":
    main()
