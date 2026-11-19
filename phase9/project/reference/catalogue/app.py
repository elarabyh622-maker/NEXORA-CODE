import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import auth, store


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=60)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

    @field_validator("name", "category")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("لا تقبل أسماء المنتجات والتصنيفات محرف NUL.")
        return value


class Product(ProductInput):
    id: int


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResult(BaseModel):
    access_token: str
    token_type: str
    role: str


bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
ProductId = Annotated[int, PathParameter(ge=1, le=2**63 - 1)]


def create_app(db_path=None):
    path = Path(db_path) if db_path is not None else store.database_path()

    @asynccontextmanager
    async def lifespan(app):
        store.initialize(path)
        yield

    app = FastAPI(title="كتالوج المنتجات", lifespan=lifespan)
    # نعدّ كل محاولة قبل فحص كلمة المرور. التطبيق محلي ويعمل بعملية واحدة.
    attempts = deque()
    attempts_lock = Lock()
    dummy_hash = auth.hash_password("unused-account-sentinel")

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        # نعيد الحقل ورسالة الخطأ، دون إعادة القيم المرسلة مثل كلمة المرور.
        errors = [{"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    def require_user(credentials: Credentials):
        if credentials:
            with store.transaction(path) as db:
                user = auth.session_user(db, credentials.credentials)
                if user:
                    return dict(user)
        raise HTTPException(401, "يلزم تسجيل الدخول.", headers={"WWW-Authenticate": "Bearer"})

    def require_admin(user=Depends(require_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "هذه العملية تتطلب حساب مسؤول.")

    @app.get("/api/products", response_model=list[Product])
    def products(q: Annotated[str, Query(max_length=100)] = "",
                 category: Annotated[str, Query(max_length=60)] = ""):
        with store.transaction(path) as db:
            return store.list_products(db, q, category)

    @app.get("/api/products/{product_id}", response_model=Product)
    def product(product_id: ProductId):
        with store.transaction(path) as db:
            row = store.get_product(db, product_id)
        if row is None:
            raise HTTPException(404, "المنتج غير موجود.")
        return row

    @app.post("/api/login", response_model=LoginResult)
    def login(data: LoginInput, response: Response):
        with attempts_lock:
            now = time.monotonic()
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 8:
                raise HTTPException(429, "انتظر دقيقة قبل المحاولة التالية.", headers={"Retry-After": "60"})
            attempts.append(now)
        with store.transaction(path) as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (data.username.strip(),)).fetchone()
            matches = auth.verify_password(data.password, user["password_hash"] if user else dummy_hash)
            if not matches or user is None:
                raise HTTPException(401, "بيانات الدخول غير صحيحة.")
            token = auth.issue_session(db, user["id"])
        response.headers["Cache-Control"] = "no-store"
        return {"access_token": token, "token_type": "bearer", "role": user["role"]}

    @app.get("/api/me")
    def me(response: Response, user=Depends(require_user)):
        response.headers["Cache-Control"] = "no-store"
        return user

    @app.post("/api/logout", status_code=204)
    def logout(credentials: Credentials, user=Depends(require_user)):
        with store.transaction(path) as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (auth.token_hash(credentials.credentials),))
        return Response(status_code=204)

    @app.post("/api/products", status_code=201, response_model=Product, dependencies=[Depends(require_admin)])
    def create_product(data: ProductInput):
        with store.transaction(path) as db:
            return store.add_product(db, **data.model_dump())

    @app.put("/api/products/{product_id}", response_model=Product, dependencies=[Depends(require_admin)])
    def replace_product(product_id: ProductId, data: ProductInput):
        with store.transaction(path) as db:
            row = store.update_product(db, product_id, **data.model_dump())
        if row is None:
            raise HTTPException(404, "المنتج غير موجود.")
        return row

    @app.delete("/api/products/{product_id}", status_code=204, dependencies=[Depends(require_admin)])
    def remove_product(product_id: ProductId):
        with store.transaction(path) as db:
            if not store.delete_product(db, product_id):
                raise HTTPException(404, "المنتج غير موجود.")
        return Response(status_code=204)

    app.mount("/", StaticFiles(directory=Path(__file__).with_name("static"), html=True), name="ui")
    return app
