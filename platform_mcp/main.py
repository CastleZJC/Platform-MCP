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
    from loguru import logger

    from platform_mcp.common.database import _ensure_engine, get_session_factory
    from platform_mcp.common.logsetup import setup_logging
    from platform_mcp.common.runtime_config import start_background_refresh

    setup_logging(get_settings())
    # 部署期注册表自检：所有配置项参数均需在系统配置注册表中且默认值可用（不允许硬代码兜底，fail-fast）
    from platform_mcp.common.runtime_config import KNOWN_KEYS, validate_registry

    problems = validate_registry()
    if problems:
        raise RuntimeError(f"系统配置注册表部署检查未通过：{'；'.join(problems)}")
    logger.info("系统配置注册表部署检查通过（{} keys）", len(KNOWN_KEYS))
    _ensure_engine()
    # 内置 Skill 启动同步：装饰器注册的 Skill 自动落库 pmcp_skill（展示链路不靠手工 seed）
    try:
        from platform_mcp.skills.bootstrap import sync_builtin_skills_to_db

        async with get_session_factory()() as session:
            inserted, refreshed = await sync_builtin_skills_to_db(session)
        if inserted or refreshed:
            logger.info("内置 Skill 启动同步：新增 {} / 刷新 {}", inserted, refreshed)
    except Exception as e:
        logger.warning("内置 Skill 启动同步失败（不阻断启动）: {}", e)
    # 部署期幂等补全：Skill 版本存档双语 README / 审核报告缺失自动补齐（失败不阻断启动）
    try:
        from platform_mcp.skills.versioning import backfill_missing_archives

        async with get_session_factory()() as session:
            filled = await backfill_missing_archives(session)
            await session.commit()
        if filled:
            logger.info("Skill 存档补全：{} 个 Skill 的双语 README / 审核报告已模板兜底补齐", filled)
    except Exception as e:
        logger.warning("Skill 存档补全失败（不阻断启动）: {}", e)
    # 广场版本归档补全：存量广场 Skill 无版本归档时按当前内容快照补一版（失败不阻断启动）
    try:
        from platform_mcp.review.service import backfill_plaza_versions

        async with get_session_factory()() as session:
            plaza_filled = await backfill_plaza_versions(session)
            await session.commit()
        if plaza_filled:
            logger.info("广场版本归档补全：{} 个广场 Skill 已按当前内容快照补一版", plaza_filled)
    except Exception as e:
        logger.warning("广场版本归档补全失败（不阻断启动）: {}", e)
    # README 迭代段落补历史：广场包 + 个人 origin=ORIGINAL 包缺「版本迭代记录」段落时补齐
    # （须在广场版本归档补全之后——段落条目依赖归档版本链；失败不阻断启动）
    try:
        from platform_mcp.skills.iteration_readme import backfill_readme_iterations

        async with get_session_factory()() as session:
            readme_filled = await backfill_readme_iterations(session)
            await session.commit()
        if readme_filled["plaza"] or readme_filled["personal"]:
            logger.info(
                "README 迭代段落补历史：广场 {} 个 / 个人 {} 个已补齐",
                readme_filled["plaza"], readme_filled["personal"],
            )
    except Exception as e:
        logger.warning("README 迭代段落补历史失败（不阻断启动）: {}", e)
    # 运行时配置中心：进程空闲期周期刷新（log.level 等即时键的应用）
    refresh_task = await start_background_refresh()
    # V3.0 M5：outbox 周期 flush（仅 Web 进程——outbox 单写多读，MCP 进程只写不发，§19.5.5）
    from platform_mcp.notify.tasks import start_outbox_flush

    notify_task = await start_outbox_flush()
    yield
    notify_task.cancel()
    refresh_task.cancel()


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
        elif path.startswith("assets/"):
            # content-hash 资源可安全长缓存（内容变→文件名变，no-cache 的 index.html 会带来新 URL）。
            # 不加则浏览器走 Last-Modified 启发式缓存，tar 部署 mtime=0 会被算成数年新鲜度，
            # 旧 entry 引用已删除 chunk 时永不回源 → 页面空白（20260816 生产事件根因）。
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


# 候选 1：CWD/platform-mcp-frontend/dist（生产部署，启动脚本 cd $APP 后 CWD 即应用根）
# 候选 2：__file__/../../platform-mcp-frontend/dist（开发模式，源码树根）
# 命名与源码项目一致：platform-mcp-frontend/（vite 项目根）+ /dist（build 产物）
_CWD_DIST = _Path.cwd() / "platform-mcp-frontend" / "dist"
_REPO_DIST = _Path(__file__).resolve().parent.parent / "platform-mcp-frontend" / "dist"
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
