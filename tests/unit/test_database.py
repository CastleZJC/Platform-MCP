"""common/database 单元测试 — get_db 依赖注入"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_db_正常yield():
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_ctx

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", mock_factory):
        from platform_mcp.common.database import get_db
        async for session in get_db():
            assert session is mock_session
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_异常时rollback():
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", mock_factory):
        from platform_mcp.common.database import get_db
        gen = get_db()
        session = await gen.asend(None)
        assert session is mock_session
        try:
            await gen.athrow(ValueError, ValueError("test"))
        except ValueError:
            pass
        mock_session.rollback.assert_called_once()
