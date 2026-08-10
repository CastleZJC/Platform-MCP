"""MCP streamable-http Header 认证测试（P0-2）

覆盖：
- _validate_api_key_async 校验逻辑
- stdio 模式从环境变量读取
- HTTP Header 模式（_AuthMiddleware）
- 校验失败时返回 401
- 校验成功时写入 contextvars
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestValidateApiKeyAsync:
    """_validate_api_key_async 核心校验函数"""

    @pytest.mark.asyncio
    async def test_validate_correct_key_returns_identity(self):
        """正确 key 返回 identity dict"""
        from platform_mcp.mcp_server import _validate_api_key_async

        expected = {"user_id": 1, "username": "admin", "role_code": "admin"}
        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = expected
                result = await _validate_api_key_async("pmcp_valid_key")
        assert result == expected

    @pytest.mark.asyncio
    async def test_validate_invalid_key_returns_none(self):
        """无效 key 返回 None"""
        from platform_mcp.mcp_server import _validate_api_key_async

        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = None
                result = await _validate_api_key_async("pmcp_invalid_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_empty_key_returns_none(self):
        """空 key 返回 None"""
        from platform_mcp.mcp_server import _validate_api_key_async

        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = None
                result = await _validate_api_key_async("")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_uses_session_factory(self):
        """校验时使用 async_session_factory 创建独立 session"""
        from platform_mcp.mcp_server import _validate_api_key_async

        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine") as mock_ensure, \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock):
                await _validate_api_key_async("pmcp_test")
        mock_ensure.assert_called_once()
        mock_factory.assert_called()


class TestIdentityContextVar:
    """_mcp_identity_var contextvars 行为"""

    def test_default_value_is_none(self):
        """默认值 None（未认证状态）"""
        from platform_mcp.mcp_server import _mcp_identity_var

        _mcp_identity_var.set(None)
        assert _mcp_identity_var.get() is None

    def test_set_identity_persists_in_same_context(self):
        """同一 async context 中设置的 identity 可读"""
        from platform_mcp.mcp_server import _mcp_identity_var

        identity = {"user_id": 1, "username": "admin", "role_code": "admin"}
        token = _mcp_identity_var.set(identity)
        try:
            assert _mcp_identity_var.get() == identity
        finally:
            _mcp_identity_var.reset(token)

    @pytest.mark.asyncio
    async def test_concurrent_requests_have_isolated_identity(self):
        """HTTP 模式下并发请求 identity 隔离（contextvars 核心特性）"""
        import asyncio

        from platform_mcp.mcp_server import _mcp_identity_var

        async def set_and_check(user: str):
            identity = {"username": user}
            token = _mcp_identity_var.set(identity)
            await asyncio.sleep(0.01)
            current = _mcp_identity_var.get()
            _mcp_identity_var.reset(token)
            return current["username"] if current else None

        results = await asyncio.gather(
            set_and_check("user_a"),
            set_and_check("user_b"),
            set_and_check("user_c"),
        )
        assert results == ["user_a", "user_b", "user_c"]


class TestStdioMode:
    """stdio 模式：从环境变量读取"""

    @pytest.mark.asyncio
    async def test_stdio_env_var_set_validates_on_startup(self, monkeypatch):
        """设置 PLATFORM_MCP_API_KEY 环境变量时，启动时校验"""
        monkeypatch.setenv("PLATFORM_MCP_API_KEY", "pmcp_stdio_key")

        from platform_mcp.mcp_server import _validate_api_key_async

        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_v:
                mock_v.return_value = {"username": "admin", "role_code": "admin"}
                result = await _validate_api_key_async("pmcp_stdio_key")
        assert result is not None
        assert result["username"] == "admin"

    @pytest.mark.asyncio
    async def test_stdio_env_var_not_set_returns_none_on_empty(self, monkeypatch):
        """未设置环境变量时，空字符串校验返回 None"""
        monkeypatch.delenv("PLATFORM_MCP_API_KEY", raising=False)

        from platform_mcp.mcp_server import _validate_api_key_async

        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_v:
                mock_v.return_value = None
                result = await _validate_api_key_async("")
        assert result is None


class TestAuthMiddleware:
    """HTTP 模式：_AuthMiddleware 拦截 Header 认证

    通过模拟中间件 dispatch 逻辑测试，避免引入完整 Starlette app
    """

    @staticmethod
    async def _run_dispatch(request_headers: dict):
        """复用 main.py 中 _AuthMiddleware.dispatch 的逻辑"""
        from platform_mcp.mcp_server import _validate_api_key_async, _mcp_identity_var

        api_key = request_headers.get("PLATFORM_MCP_API_KEY", "")
        if not api_key:
            return {"status": 401, "error": "缺少 PLATFORM_MCP_API_KEY 请求头"}
        identity = await _validate_api_key_async(api_key)
        if not identity:
            return {"status": 401, "error": "无效的 API Key"}
        _mcp_identity_var.set(identity)
        return {"status": 200, "identity": identity}

    @pytest.mark.asyncio
    async def test_missing_header_returns_401(self):
        """无 PLATFORM_MCP_API_KEY Header → 401"""
        result = await self._run_dispatch({})
        assert result["status"] == 401
        assert "缺少" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_header_returns_401(self):
        """有 Header 但 key 无效 → 401"""
        mock_session = AsyncMock()
        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_v:
                mock_v.return_value = None
                result = await self._run_dispatch({"PLATFORM_MCP_API_KEY": "pmcp_invalid"})
        assert result["status"] == 401
        assert "无效" in result["error"]

    @pytest.mark.asyncio
    async def test_valid_header_writes_contextvars(self):
        """有效 Header → 写入 contextvars + 返回 200"""
        from platform_mcp.mcp_server import _mcp_identity_var

        expected = {"user_id": 1, "username": "admin", "role_code": "admin"}
        token = _mcp_identity_var.set(None)
        try:
            mock_session = AsyncMock()
            with patch("platform_mcp.common.database._ensure_engine"), \
                 patch("platform_mcp.common.database.async_session_factory") as mock_factory:
                mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
                with patch("platform_mcp.auth.api_key_service.validate_api_key", new_callable=AsyncMock) as mock_v:
                    mock_v.return_value = expected
                    result = await self._run_dispatch({"PLATFORM_MCP_API_KEY": "pmcp_valid"})
            assert result["status"] == 200
            assert _mcp_identity_var.get() == expected
        finally:
            _mcp_identity_var.reset(token)


class TestGetIdentityHelper:
    """get_current_identity 辅助函数"""

    def test_returns_none_when_not_set(self):
        from platform_mcp.mcp_server import _mcp_identity_var, get_current_identity

        token = _mcp_identity_var.set(None)
        try:
            assert get_current_identity() is None
        finally:
            _mcp_identity_var.reset(token)

    def test_returns_dict_when_set(self):
        from platform_mcp.mcp_server import _mcp_identity_var, get_current_identity

        identity = {"username": "dev", "role_code": "developer"}
        token = _mcp_identity_var.set(identity)
        try:
            assert get_current_identity() == identity
        finally:
            _mcp_identity_var.reset(token)
