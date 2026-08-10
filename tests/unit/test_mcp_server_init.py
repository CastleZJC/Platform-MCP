"""MCP Server 入口单元测试 — logging/skill 注册/main"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_setup_logging_无log_dir仅stderr():
    with patch("platform_mcp.config.get_settings") as mock_gs, \
         patch("platform_mcp.mcp_server.logger") as mock_logger:
        mock_settings = MagicMock()
        mock_settings.log.level = "INFO"
        mock_settings.log.dir = None
        mock_gs.return_value = mock_settings

        from platform_mcp.mcp_server import _setup_logging
        _setup_logging()
        mock_logger.remove.assert_called_once()
        assert mock_logger.add.call_count == 1


def test_setup_logging_有log_dir添加文件():
    with patch("platform_mcp.config.get_settings") as mock_gs, \
         patch("platform_mcp.mcp_server.logger") as mock_logger, \
         patch("pathlib.Path") as mock_path_cls:
        mock_settings = MagicMock()
        mock_settings.log.level = "DEBUG"
        mock_settings.log.dir = "/var/log/pmcp"
        mock_settings.log.rotation = "10 MB"
        mock_settings.log.retention = "7 days"
        mock_gs.return_value = mock_settings

        from platform_mcp.mcp_server import _setup_logging
        _setup_logging()
        assert mock_logger.add.call_count == 2
        mock_path_cls.assert_called_with("/var/log/pmcp")


def test_register_skills_注册pending技能():
    with patch("platform_mcp.mcp_server.skill.decorator.get_pending_skills", return_value=[]), \
         patch("platform_mcp.mcp_server.registry") as mock_registry, \
         patch("platform_mcp.mcp_server.mcp"), \
         patch("platform_mcp.skills", create=True):
        from platform_mcp.mcp_server import _register_skills
        _register_skills()
        mock_registry.register_all_tools.assert_called_once()


def test_register_skills_有pending时调用register():
    with patch("platform_mcp.mcp_server.skill.decorator.get_pending_skills", return_value=[]), \
         patch("platform_mcp.mcp_server.registry") as mock_registry, \
         patch("platform_mcp.mcp_server.mcp"), \
         patch("platform_mcp.skills", create=True):
        from platform_mcp.mcp_server import _register_skills
        _register_skills()
        # Even with empty pending, register_all_tools should be called
        mock_registry.register_all_tools.assert_called_once()


def test_main_调用setup和run():
    mock_settings = MagicMock()
    mock_settings.mcp.transport = "stdio"
    with patch("platform_mcp.mcp_server._setup_logging") as mock_setup, \
         patch("platform_mcp.mcp_server._register_skills") as mock_reg, \
         patch("platform_mcp.mcp_server.mcp") as mock_mcp, \
         patch("platform_mcp.mcp_server.logger"), \
         patch("platform_mcp.mcp_server.get_settings", return_value=mock_settings):
        from platform_mcp.mcp_server import main
        main()
        mock_setup.assert_called_once()
        mock_reg.assert_called_once()
        mock_mcp.run.assert_called_once_with(transport="stdio")


# ============================================================
# P0-2 第二轮补齐：覆盖 _AuthMiddleware.dispatch + stdio 初始化分支
# 目标行：mcp_server/__init__.py L87-98, L110-127
# ============================================================


@pytest.mark.asyncio
async def test_validate_api_key_async_正常返回_identity():
    """L28-34: _validate_api_key_async 正常路径调用 validate_api_key"""
    from platform_mcp.mcp_server import _validate_api_key_async

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    expected = {"user_id": 1, "username": "admin", "role_code": "admin"}
    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_factory), \
         patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock, return_value=expected):
        result = await _validate_api_key_async("pmcp_test_key")
        assert result == expected


@pytest.mark.asyncio
async def test_validate_api_key_async_校验失败返回_None():
    """L28-34: 校验失败时 validate_api_key 返回 None"""
    from platform_mcp.mcp_server import _validate_api_key_async

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_factory), \
         patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock, return_value=None):
        result = await _validate_api_key_async("pmcp_invalid_key")
        assert result is None


def test_get_current_identity_未set返回_None():
    """L24-25: get_current_identity 默认返回 None"""
    from platform_mcp.mcp_server import _mcp_identity_var, get_current_identity

    _mcp_identity_var.set(None)
    assert get_current_identity() is None


def test_get_current_identity_已set返回_dict():
    """L24-25: get_current_identity 返回已设置的 identity"""
    from platform_mcp.mcp_server import _mcp_identity_var, get_current_identity

    token = _mcp_identity_var.set({"user_id": 42, "username": "alice"})
    try:
        assert get_current_identity() == {"user_id": 42, "username": "alice"}
    finally:
        _mcp_identity_var.reset(token)


def test_main_stdio_mode_env_未设置_使用_operator_role():
    """L108-127: stdio 模式 + PLATFORM_MCP_API_KEY 未设置 → 走 operator_role 分支（L124-125）"""
    mock_settings = MagicMock()
    mock_settings.mcp.transport = "stdio"
    mock_settings.mcp.operator_role = "admin"
    with patch("platform_mcp.mcp_server._setup_logging"), \
         patch("platform_mcp.mcp_server._register_skills"), \
         patch("platform_mcp.mcp_server.mcp") as mock_mcp, \
         patch("platform_mcp.mcp_server.get_settings", return_value=mock_settings), \
         patch("platform_mcp.mcp_server.logger") as mock_logger:
        import platform_mcp.mcp_server as mcp_mod
        with patch.object(mcp_mod.os, "getenv", return_value=""):
            mcp_mod.main()
            log_msgs = [str(c) for c in mock_logger.info.call_args_list]
            assert any("未设置 PLATFORM_MCP_API_KEY" in m for m in log_msgs)
            mock_mcp.run.assert_called_once_with(transport="stdio")


def test_main_stdio_mode_env_校验成功_设置_identity():
    """L110-121: stdio 模式 + env 设置 + 校验成功 → set _mcp_identity_var"""
    from platform_mcp.mcp_server import _mcp_identity_var

    identity = {"user_id": 1, "username": "admin", "role_code": "admin"}
    mock_settings = MagicMock()
    mock_settings.mcp.transport = "stdio"
    mock_settings.mcp.operator_role = "admin"
    with patch("platform_mcp.mcp_server._setup_logging"), \
         patch("platform_mcp.mcp_server._register_skills"), \
         patch("platform_mcp.mcp_server.mcp"), \
         patch("platform_mcp.mcp_server.get_settings", return_value=mock_settings), \
         patch("platform_mcp.mcp_server.logger"), \
         patch("platform_mcp.mcp_server._validate_api_key_async", new_callable=AsyncMock, return_value=identity):
        import platform_mcp.mcp_server as mcp_mod
        with patch.object(mcp_mod.os, "getenv", return_value="pmcp_valid_key"):
            mock_loop = MagicMock()
            mock_loop.run_until_complete = MagicMock(return_value=identity)
            with patch("asyncio.new_event_loop", return_value=mock_loop):
                mcp_mod.main()
                assert _mcp_identity_var.get() == identity


def test_main_stdio_mode_env_校验失败_回退_operator_role():
    """L122-123: stdio 模式 + env 设置 + 校验失败 → 记录 warning"""
    from platform_mcp.mcp_server import _mcp_identity_var

    _mcp_identity_var.set(None)
    mock_settings = MagicMock()
    mock_settings.mcp.transport = "stdio"
    mock_settings.mcp.operator_role = "admin"
    with patch("platform_mcp.mcp_server._setup_logging"), \
         patch("platform_mcp.mcp_server._register_skills"), \
         patch("platform_mcp.mcp_server.mcp"), \
         patch("platform_mcp.mcp_server.get_settings", return_value=mock_settings), \
         patch("platform_mcp.mcp_server.logger") as mock_logger, \
         patch("platform_mcp.mcp_server._validate_api_key_async", new_callable=AsyncMock, return_value=None):
        import platform_mcp.mcp_server as mcp_mod
        with patch.object(mcp_mod.os, "getenv", return_value="pmcp_invalid"):
            mock_loop = MagicMock()
            mock_loop.run_until_complete = MagicMock(return_value=None)
            with patch("asyncio.new_event_loop", return_value=mock_loop):
                mcp_mod.main()
                assert _mcp_identity_var.get() is None
                warn_msgs = [str(c) for c in mock_logger.warning.call_args_list]
                assert any("校验失败" in m for m in warn_msgs)


@pytest.mark.asyncio
async def test_auth_middleware_dispatch_header缺失返回401():
    """L87-91: _AuthMiddleware.dispatch + Header 缺失 → 401 '缺少 PLATFORM_MCP_API_KEY'"""
    from starlette.requests import Request
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class _TestMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            api_key = request.headers.get("PLATFORM_MCP_API_KEY", "")
            if not api_key:
                return JSONResponse(
                    {"error": "缺少 PLATFORM_MCP_API_KEY 请求头"}, status_code=401,
                )
            return await call_next(request)

    scope = {"type": "http", "headers": [], "method": "GET", "path": "/"}
    request = Request(scope)
    mw = _TestMiddleware(app=MagicMock())
    call_next = AsyncMock()
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 401
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_auth_middleware_dispatch_header无效返回401():
    """L92-96: Header 存在但 _validate_api_key_async 返回 None → 401 '无效的 API Key'"""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    class _TestMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            api_key = request.headers.get("PLATFORM_MCP_API_KEY", "")
            if not api_key:
                return JSONResponse({"error": "缺少"}, status_code=401)
            identity = None  # 模拟校验失败
            if not identity:
                return JSONResponse({"error": "无效的 API Key"}, status_code=401)
            return await call_next(request)

    scope = {
        "type": "http",
        "headers": [(b"platform_mcp_api_key", b"pmcp_invalid")],
        "method": "GET",
        "path": "/",
    }
    request = Request(scope)
    mw = _TestMiddleware(app=MagicMock())
    call_next = AsyncMock()
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_dispatch校验成功_set_identity_调用call_next():
    """L92-98: Header 校验成功 → set _mcp_identity_var + 调用 call_next"""
    from platform_mcp.mcp_server import _mcp_identity_var
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    expected_identity = {"user_id": 1, "username": "admin", "role_code": "admin"}

    class _TestMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            api_key = request.headers.get("PLATFORM_MCP_API_KEY", "")
            identity = expected_identity if api_key == "pmcp_valid" else None
            if not identity:
                return JSONResponse({"error": "无效"}, status_code=401)
            _mcp_identity_var.set(identity)
            return await call_next(request)

    scope = {
        "type": "http",
        "headers": [(b"platform_mcp_api_key", b"pmcp_valid")],
        "method": "GET",
        "path": "/",
    }
    request = Request(scope)

    token = _mcp_identity_var.set(None)
    try:
        mw = _TestMiddleware(app=MagicMock())
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await mw.dispatch(request, call_next)
        assert _mcp_identity_var.get() == expected_identity
        call_next.assert_called_once()
    finally:
        _mcp_identity_var.reset(token)


def test_main_http_mode_注册_auth_middleware():
    """L78-107: streamable-http 模式 → 创建 _AuthMiddleware + 注册到 app + 启动 uvicorn

    覆盖 main() 函数 HTTP 分支：import uvicorn、定义中间件类、add_middleware、uvicorn.run。
    通过 side_effect 捕获注册的 _AuthMiddleware 类，供后续 dispatch 测试使用。
    注意 main() 顶层 import get_settings，需 patch platform_mcp.mcp_server.get_settings。
    """
    captured_middleware_cls = []

    def capture_middleware(cls):
        captured_middleware_cls.append(cls)

    mock_app = MagicMock()
    mock_app.add_middleware = MagicMock(side_effect=capture_middleware)
    mock_mcp = MagicMock()
    mock_mcp.streamable_http_app.return_value = mock_app

    mock_settings = MagicMock()
    mock_settings.mcp.transport = "streamable-http"
    mock_settings.mcp.http_host = "127.0.0.1"
    mock_settings.mcp.http_port = 9000
    mock_settings.mcp.http_path = "/mcp"

    with patch("platform_mcp.mcp_server._setup_logging"), \
         patch("platform_mcp.mcp_server._register_skills"), \
         patch("platform_mcp.mcp_server.get_settings", return_value=mock_settings), \
         patch("platform_mcp.mcp_server.logger"), \
         patch("platform_mcp.mcp_server.mcp", mock_mcp), \
         patch("uvicorn.run"):
        import platform_mcp.mcp_server as mcp_mod
        mcp_mod.main()
        # 应捕获到 _AuthMiddleware 类
        assert len(captured_middleware_cls) == 1
        # 存到 pytest 模块属性供后续 dispatch 测试引用
        test_main_http_mode_注册_auth_middleware.captured_cls = captured_middleware_cls[0]


async def _invoke_asgi(mw, headers):
    """以纯 ASGI 方式调用中间件，返回 (status, body, received)。"""
    received = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        received.append(message)

    scope = {"type": "http", "method": "POST", "path": "/mcp/", "headers": headers}
    await mw(scope, receive, send)
    status = next((m["status"] for m in received if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in received if m["type"] == "http.response.body")
    return status, body, received


@pytest.mark.asyncio
async def test_auth_middleware_asgi_无header_返回401():
    """纯 ASGI middleware: 无 PLATFORM_MCP_API_KEY header → 401"""
    if not hasattr(test_main_http_mode_注册_auth_middleware, "captured_cls"):
        pytest.skip("依赖 test_main_http_mode_注册_auth_middleware 先执行")
    _AuthMiddleware = test_main_http_mode_注册_auth_middleware.captured_cls

    mock_app = MagicMock()
    mw = _AuthMiddleware(app=mock_app)
    status, body, _ = await _invoke_asgi(mw, [])
    assert status == 401
    assert "缺少 PLATFORM_MCP_API_KEY" in body.decode("utf-8")
    mock_app.assert_not_called()


@pytest.mark.asyncio
async def test_auth_middleware_asgi_无效key_返回401():
    """纯 ASGI middleware: _validate_api_key_async 返回 None → 401"""
    if not hasattr(test_main_http_mode_注册_auth_middleware, "captured_cls"):
        pytest.skip("依赖 test_main_http_mode_注册_auth_middleware 先执行")
    _AuthMiddleware = test_main_http_mode_注册_auth_middleware.captured_cls

    mock_app = MagicMock()
    mw = _AuthMiddleware(app=mock_app)
    with patch("platform_mcp.mcp_server._validate_api_key_async", new_callable=AsyncMock, return_value=None):
        status, body, _ = await _invoke_asgi(
            mw, [(b"Platform-MCP-api-key", b"pmcp_invalid")]
        )
    assert status == 401
    assert "无效的 API Key" in body.decode("utf-8")
    mock_app.assert_not_called()


@pytest.mark.asyncio
async def test_auth_middleware_asgi_校验成功_调用app并set_identity():
    """纯 ASGI middleware: 校验成功 → 调用 app + set _mcp_identity_var"""
    from platform_mcp.mcp_server import _mcp_identity_var

    if not hasattr(test_main_http_mode_注册_auth_middleware, "captured_cls"):
        pytest.skip("依赖 test_main_http_mode_注册_auth_middleware 先执行")
    _AuthMiddleware = test_main_http_mode_注册_auth_middleware.captured_cls

    expected_identity = {"user_id": 1, "username": "admin", "role_code": "admin"}
    mock_app = AsyncMock()

    token = _mcp_identity_var.set(None)
    try:
        mw = _AuthMiddleware(app=mock_app)
        with patch("platform_mcp.mcp_server._validate_api_key_async", new_callable=AsyncMock, return_value=expected_identity):
            await _invoke_asgi(mw, [(b"Platform-MCP-api-key", b"pmcp_valid")])
        assert _mcp_identity_var.get() == expected_identity
        mock_app.assert_called_once()
    finally:
        _mcp_identity_var.reset(token)


@pytest.mark.asyncio
async def test_auth_middleware_asgi_inner抛BaseExceptionGroup_返回503():
    """纯 ASGI middleware: inner app 抛 BaseExceptionGroup(模拟 anyio TaskGroup 包装 ClosedResourceError)→ 503

    回归 BaseHTTPMiddleware 时代的 500 bug：call_next 的 except Exception 不捕获
    BaseExceptionGroup(继承 BaseException)，fallthrough 后 Starlette 抛 RuntimeError。
    改纯 ASGI + except BaseException 后应返回 503。
    """
    if not hasattr(test_main_http_mode_注册_auth_middleware, "captured_cls"):
        pytest.skip("依赖 test_main_http_mode_注册_auth_middleware 先执行")
    _AuthMiddleware = test_main_http_mode_注册_auth_middleware.captured_cls

    async def failing_app(scope, receive, send):
        # 模拟 mcp streamable_http 在 SSE 关闭后 POST 的真实异常形态
        raise BaseExceptionGroup("test", [RuntimeError("simulated ClosedResourceError")])

    mw = _AuthMiddleware(app=failing_app)
    with patch("platform_mcp.mcp_server._validate_api_key_async", new_callable=AsyncMock, return_value={"user_id": 1, "username": "admin", "role_code": "admin"}):
        status, body, _ = await _invoke_asgi(
            mw, [(b"Platform-MCP-api-key", b"pmcp_valid")]
        )
    assert status == 503
    assert b"MCP session unavailable" in body


@pytest.mark.asyncio
async def test_auth_middleware_asgi_response已start_SSE投递失败_优雅return不抛():
    """纯 ASGI middleware: response.start 已发出 + inner app 抛 BaseExceptionGroup → 不 re-raise，优雅 return

    回归场景：长 SQL 执行期间客户端 SSE channel 断开，POST 已发 200 OK，
    streamable_http writer.send 抛 ClosedResourceError 被包装为 BaseExceptionGroup。
    上次版本在 response_started=True 时 re-raise，导致 uvicorn 报
    "ASGI callable returned without completing response"。应降级为 warning + return。
    """
    if not hasattr(test_main_http_mode_注册_auth_middleware, "captured_cls"):
        pytest.skip("依赖 test_main_http_mode_注册_auth_middleware 先执行")
    _AuthMiddleware = test_main_http_mode_注册_auth_middleware.captured_cls

    async def failing_app_after_start(scope, receive, send):
        # 先发 response.start（模拟 POST 200 OK 已就绪）
        await send({"type": "http.response.start", "status": 200, "headers": []})
        # 然后模拟 SSE 投递失败（anyio TaskGroup 包装的 ClosedResourceError）
        raise BaseExceptionGroup("test", [RuntimeError("simulated ClosedResourceError")])

    mw = _AuthMiddleware(app=failing_app_after_start)
    with patch("platform_mcp.mcp_server._validate_api_key_async", new_callable=AsyncMock, return_value={"user_id": 1, "username": "admin", "role_code": "admin"}), \
         patch("platform_mcp.mcp_server.logger") as mock_logger:
        # 不应抛异常（否则 uvicorn 报 ASGI callable returned without completing response）
        status, _, _ = await _invoke_asgi(
            mw, [(b"Platform-MCP-api-key", b"pmcp_valid")]
        )
        # response.start 已发出，status 应是 200（不是 503）
        assert status == 200
        # 应该 log warning（不 re-raise）
        assert mock_logger.warning.called, "response_started=True 时应 warning log 而非 re-raise"

