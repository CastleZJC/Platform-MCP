"""Platform-MCP FastAPI Web 入口"""

import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from platform_mcp.common.exceptions import BaseError
from platform_mcp.common.response import ResponseBase
from platform_mcp.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _setup_logging(settings)
    from platform_mcp.common.database import _ensure_engine

    _ensure_engine()
    yield


def _setup_logging(settings) -> None:
    import sys

    from loguru import logger

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log.level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    log_dir = settings.log.dir
    if log_dir:
        from pathlib import Path

        Path(log_dir).mkdir(exist_ok=True)
        logger.add(
            f"{log_dir}/Platform-MCP-{{time:YYYY-MM-DD}}.log",
            level=settings.log.level,
            rotation=settings.log.rotation,
            retention=settings.log.retention,
            encoding="utf-8",
        )


app = FastAPI(
    title=settings.name,
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Task 1.3.3: 全局异常处理器
@app.exception_handler(BaseError)
async def base_error_handler(request: Request, exc: BaseError):
    return JSONResponse(
        status_code=400,
        content=ResponseBase(
            code=exc.error_code,
            message=exc.message,
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=ResponseBase(
            code=15001,
            message=f"内部错误: {exc}",
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(),
    )


# Task 1.3.7: TraceId 中间件
class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response


app.add_middleware(TraceIdMiddleware)


# 注册 API 路由
from platform_mcp.api import register_api_routes

register_api_routes(app)


@app.get("/api/v1/health")
async def health():
    return {"status": "UP"}


# 静态前端：仅当 ui/dist 存在时挂载（开发环境不挂，前端走 Vite 5173）
# 生产部署同端口 8080 同时承担 API + 前端，弃用 Nginx（详见部署规范 §13.8）
# 关键：Starlette StaticFiles(html=True) 只对根 "/" fallback 到 index.html，
# 对 /datasources /users 这类 SPA 子路径直接 404；需子类化做 SPA fallback
from pathlib import Path as _Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402


class _SpaStaticFiles(StaticFiles):
    """SPA 兜底：找不到的文件路径（且不是 /assets/* 静态资源）回 index.html，
    交给前端 vue-router 处理。/api/v1/* 在本 mount 之前已注册，不会进到这里。"""

    async def get_response(self, path, scope):
        from starlette.exceptions import HTTPException as _StarletteHTTPException
        try:
            response = await super().get_response(path, scope)
        except _StarletteHTTPException as e:
            if e.status_code == 404 and not path.startswith(("assets/", "favicon", "icons", "vite.svg")):
                response = await super().get_response("index.html", scope)
            else:
                raise
        # SPA entry（index.html）不能缓存：vite 用 content-hash 命名 chunk，
        # 旧 index.html 引用旧 hash → 部署后 chunk 404。所有 text/html 响应都加 no-cache。
        ctype = response.headers.get("content-type", "")
        if "text/html" in ctype:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


# 候选 1：CWD/Platform-MCP-frontend/dist（生产部署，启动脚本 cd $APP 后 CWD 即应用根）
# 候选 2：__file__/../../Platform-MCP-frontend/dist（开发模式，源码树根）
# 命名与源码项目一致：Platform-MCP-frontend/（vite 项目根）+ /dist（build 产物）
_CWD_DIST = _Path.cwd() / "Platform-MCP-frontend" / "dist"
_REPO_DIST = _Path(__file__).resolve().parent.parent / "Platform-MCP-frontend" / "dist"
_UI_DIST = _CWD_DIST if _CWD_DIST.exists() else _REPO_DIST
if _UI_DIST.exists():
    app.mount("/", _SpaStaticFiles(directory=str(_UI_DIST), html=True), name="ui")


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "platform_mcp.main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
    )
