"""MCP Server 入口 — 整合 Skill Registry、配置加载、Tool 注册、API Key 认证"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import sys

from loguru import logger
from mcp.server.fastmcp import FastMCP

from platform_mcp.config import get_settings
from platform_mcp.mcp_server.skill.decorator import get_pending_skills
from platform_mcp.mcp_server.skill.registry import registry

mcp = FastMCP("Platform-MCP")

# 用 ContextVar 保证 async 并发安全（HTTP 模式每请求独立；stdio 模式全局唯一）
_mcp_identity_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_identity", default=None
)


def get_current_identity() -> dict | None:
    return _mcp_identity_var.get()


async def _validate_api_key_async(key_string: str) -> dict | None:
    from platform_mcp.auth.api_key_service import validate_api_key
    from platform_mcp.common import database as _db

    async with _db.get_session_factory()() as session:
        return await validate_api_key(session, key_string)


async def _send_json_response(send, status: int, body: dict) -> None:
    """通过原始 ASGI send 发送 JSON 响应（绕过 BaseHTTPMiddleware）。"""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class _AuthMiddleware:
    """纯 ASGI 鉴权中间件（兼容 MCP streamable_http 的 ExceptionGroup）。

    为何不用 starlette.BaseHTTPMiddleware：
    MCP SDK 1.9.4 的 streamable_http_app 在 SSE 长连接关闭后客户端仍发 POST 时，
    _handle_post_request 抛 anyio.ClosedResourceError，被 anyio TaskGroup 包装为
    BaseExceptionGroup（继承 BaseException 而非 Exception）。BaseHTTPMiddleware.call_next
    的 `except Exception` 无法捕获 BaseExceptionGroup，fallthrough 后抛
    `RuntimeError("No response returned.")`，最终被 Starlette 升级为 HTTP 500。

    改为纯 ASGI callable：直接 await self.app(...)，try/except 捕获 BaseException
    （排除 SystemExit/KeyboardInterrupt/CancelledError），返回 503 引导客户端重建 SSE 重试。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # 从 ASGI scope 直接读 headers。ASGI 已将 name 小写，但保留下划线/连字符原样。
        # 项目约定 PLATFORM_MCP_API_KEY（下划线），同时兼容 HTTP 标准 dashes 命名。
        api_key = ""
        for name, value in scope.get("headers", []):
            if name in (b"platform_mcp_api_key", b"Platform-MCP-api-key"):
                api_key = value.decode("latin-1")
                break

        if not api_key:
            await _send_json_response(
                send, 401, {"error": "缺少 PLATFORM_MCP_API_KEY 请求头"}
            )
            return

        identity = await _validate_api_key_async(api_key)
        if not identity:
            await _send_json_response(send, 401, {"error": "无效的 API Key"})
            return

        _mcp_identity_var.set(identity)

        # 跟踪 response 是否已开始，避免对已开始的 response 二次发送
        response_started = {"value": False}

        async def _send_wrapper(message):
            if message.get("type") == "http.response.start":
                response_started["value"] = True
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        except (SystemExit, KeyboardInterrupt, asyncio.CancelledError):
            raise
        except BaseException:
            # anyio TaskGroup 在 inner app 抛 ClosedResourceError（SSE channel
            # 在客户端断开后 POST 仍写入）时包装为 BaseExceptionGroup。
            if response_started["value"]:
                # Response 已开始（典型：POST 200 + SSE 流），但 SSE 投递失败。
                # 此时无法替换响应（违反 ASGI 协议），且 re-raise 会让 uvicorn 报
                # "ASGI callable returned without completing response"，客户端会
                # 看到响应中断、超时后重连。降级为 warning + 优雅 return，让连接
                # 自然关闭，客户端会触发 SSE 重连/超时重试。
                logger.warning(
                    "MCP SSE response interrupted after start "
                    "(likely client channel closed mid-stream); "
                    "client should retry on new session",
                    exc_info=True,
                )
                return
            # Response 未开始：返回 503 引导客户端重建 SSE 重试
            logger.warning(
                "MCP streamable_http raised exception, returning 503",
                exc_info=True,
            )
            await _send_json_response(
                send, 503, {"error": "MCP session unavailable, please retry"}
            )


def _setup_logging() -> None:
    from platform_mcp.config import get_settings

    settings = get_settings()
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
            f"{log_dir}/Platform-MCP-mcp-{{time:YYYY-MM-DD}}.log",
            level=settings.log.level,
            rotation=settings.log.rotation,
            retention=settings.log.retention,
            encoding="utf-8",
        )


def _register_skills() -> None:
    """导入 skills 包触发装饰器注册，然后将 Skill 注册到 Registry。"""
    import platform_mcp.skills  # noqa: F401 — 触发 @register_skill 装饰器

    pending = get_pending_skills()
    for skill_cls in pending:
        instance = skill_cls()
        registry.register(instance)

    registry.register_all_tools(mcp)


def main() -> None:
    _setup_logging()
    _register_skills()
    settings = get_settings()

    if settings.mcp.transport == "streamable-http":
        # HTTP 模式：纯 ASGI 中间件校验每次请求的 PLATFORM_MCP_API_KEY Header
        import uvicorn

        # FastMCP 不支持 add_middleware；改拿底层 Starlette app 再加中间件
        app = mcp.streamable_http_app()
        # 文件中转端点（BUG20260814163941）：与 /mcp/ 共端口，同受 _AuthMiddleware 保护
        from platform_mcp.mcp_server.transfer import build_transfer_routes

        app.routes.extend(build_transfer_routes())
        app.add_middleware(_AuthMiddleware)
        logger.info(
            "Platform-MCP MCP Server starting (streamable-http) on {}:{}{}",
            settings.mcp.http_host, settings.mcp.http_port, settings.mcp.http_path,
        )
        uvicorn.run(app, host=settings.mcp.http_host, port=settings.mcp.http_port)
    else:
        # stdio 模式：启动时从环境变量读取 API Key，进程级绑定身份
        api_key = os.getenv("PLATFORM_MCP_API_KEY", "")
        if api_key:
            import asyncio
            loop = asyncio.new_event_loop()
            identity = loop.run_until_complete(_validate_api_key_async(api_key))
            loop.close()
            if identity:
                _mcp_identity_var.set(identity)
                logger.info(
                    "MCP Auth: user={} role={} (via PLATFORM_MCP_API_KEY)",
                    identity["username"], identity["role_code"],
                )
            else:
                logger.warning("MCP Auth: PLATFORM_MCP_API_KEY 校验失败，回退到默认 operator_role")
        else:
            logger.info("MCP Auth: 未设置 PLATFORM_MCP_API_KEY，使用默认 operator_role={}", settings.mcp.operator_role)
        logger.info("Platform-MCP MCP Server starting (stdio mode)...")
        mcp.run(transport="stdio")
