"""Unified knowledge platform API and same-origin production frontend."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from atguigu.business.api import router
from atguigu.business.knowledge_api import router as knowledge_router
from atguigu.business.import_api import router as import_router
from atguigu.business.chat_api import router as chat_router
from atguigu.business.dashboard_api import router as dashboard_router
from atguigu.business.settlement_api import router as settlement_router
from atguigu.business.security import Db, jwt_secret
from atguigu.config.config import RuntimeConfig

app = FastAPI(title="知识库管理平台", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=RuntimeConfig.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(router)
app.include_router(knowledge_router)
app.include_router(import_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(settlement_router)


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "记录编码重复或仍有关联数据"})


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"detail": "数据库暂不可用或迁移未完成"})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Pydantic's default input field can echo a submitted password or token.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
    ]})


@app.get("/health")
def health():
    return {"status": "ok", "service": "platform", "stage": 7}


@app.get("/ready")
def ready(db: Db):
    jwt_secret()
    revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != "0005":
        return JSONResponse(status_code=503, content={"detail": "数据库迁移版本不匹配"})
    return {"status": "ready", "database_revision": revision}


# A production build can share the API origin; deep links retain Vue routing.
class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        path = path.replace("\\", "/").lstrip("/")
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "接口不存在"})
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1] or scope["method"] not in {"GET", "HEAD"}:
                raise
            return FileResponse(Path(self.directory) / "index.html", headers={"Cache-Control": "no-cache"})


frontend_build = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if (frontend_build / "index.html").is_file():
    app.mount("/", FrontendFiles(directory=frontend_build, html=True), name="frontend")
