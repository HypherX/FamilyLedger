"""本地账本服务。

源码运行：
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
桌面窗口：
    python desktop.py
"""
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import desktop_session, paths
from .database import init_db
from .routes import router
from .version import VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("familyledger")


def _sanitize_no_proxy() -> None:
    for key in ("no_proxy", "NO_PROXY"):
        value = os.environ.get(key)
        if not value:
            continue
        kept = [item.strip() for item in value.split(",") if item.strip() and ":" not in item.strip()]
        if not kept:
            os.environ.pop(key, None)
        elif len(kept) != len([item for item in value.split(",") if item.strip()]):
            os.environ[key] = ",".join(kept)


_sanitize_no_proxy()


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if sys.version_info < (3, 12):
        raise RuntimeError("需要 Python 3.12 或更新版本")
    init_db()
    logger.info("家庭账本 %s，数据目录 %s", VERSION, paths.data_dir())
    yield


app = FastAPI(title="家庭账本", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(desktop_session.DesktopSessionMiddleware)
app.include_router(router)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "请求不正确"
    return JSONResponse({"detail": detail}, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def fastapi_error(_request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "请求不正确"
    return JSONResponse({"detail": detail}, status_code=exc.status_code)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION, "data_dir": str(paths.data_dir())}


app.mount("/", NoCacheStaticFiles(directory=str(paths.project_root() / "static"), html=True), name="static")
