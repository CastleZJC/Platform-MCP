"""认证业务逻辑单元测试 — authenticate_user"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_authenticate_user_成功返回用户():
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "admin"
    mock_user.nickname = "管理员"
    mock_user.password = "$2b$12$hashed"
    mock_user.status = 1

    mock_session = AsyncMock()
    mock_user_result = MagicMock()
    mock_user_result.scalar_one_or_none.return_value = mock_user
    mock_role_result = MagicMock()
    mock_role_result.scalar_one_or_none.return_value = "admin"

    mock_session.execute = AsyncMock(side_effect=[mock_user_result, mock_role_result])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx), \
         patch("platform_mcp.auth.service.verify_password", return_value=True):
        from platform_mcp.auth.service import authenticate_user
        result = await authenticate_user("admin", "password")
        assert result is not None
        assert result["username"] == "admin"
        assert result["role_code"] == "admin"


@pytest.mark.asyncio
async def test_authenticate_user_用户不存在返回None():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx):
        from platform_mcp.auth.service import authenticate_user
        result = await authenticate_user("nobody", "pass")
        assert result is None


@pytest.mark.asyncio
async def test_authenticate_user_密码错误返回None():
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "admin"
    mock_user.password = "$2b$12$hashed"
    mock_user.status = 1

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx), \
         patch("platform_mcp.auth.service.verify_password", return_value=False):
        from platform_mcp.auth.service import authenticate_user
        result = await authenticate_user("admin", "wrong")
        assert result is None


@pytest.mark.asyncio
async def test_authenticate_user_无角色默认developer():
    mock_user = MagicMock()
    mock_user.id = 2
    mock_user.username = "dev01"
    mock_user.nickname = "开发"
    mock_user.password = "$2b$12$hashed"
    mock_user.status = 1

    mock_session = AsyncMock()
    mock_user_result = MagicMock()
    mock_user_result.scalar_one_or_none.return_value = mock_user
    mock_role_result = MagicMock()
    mock_role_result.scalar_one_or_none.return_value = None

    mock_session.execute = AsyncMock(side_effect=[mock_user_result, mock_role_result])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx), \
         patch("platform_mcp.auth.service.verify_password", return_value=True):
        from platform_mcp.auth.service import authenticate_user
        result = await authenticate_user("dev01", "pass")
        assert result["role_code"] == "developer"
