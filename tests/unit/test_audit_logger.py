"""审计日志写入单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_write_audit_log_正常写入():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx):
        from platform_mcp.audit.logger import write_audit_log
        await write_audit_log(
            trace_id="t1", operator="admin", tool_name="execute_sql_text",
            result_status="success", duration_ms=100,
        )
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

        log_obj = mock_session.add.call_args[0][0]
        assert log_obj.trace_id == "t1"
        assert log_obj.operator == "admin"
        assert log_obj.tool_name == "execute_sql_text"
        assert log_obj.result_status == "success"
        assert log_obj.duration_ms == 100


@pytest.mark.asyncio
async def test_write_audit_log_参数正确传递():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx):
        from platform_mcp.audit.logger import write_audit_log
        await write_audit_log(
            trace_id="t2", request_id="r2", operator="dev01",
            skill_name="database", tool_name="validate_sql",
            resource_type="datasource", resource_id="ds1",
            env_code="DEV", request_summary="validate SELECT",
            result_status="error", risk_level="LOW",
            error_code="12001", error_message="not found",
            extra_data={"key": "val"}, duration_ms=50,
        )
        log_obj = mock_session.add.call_args[0][0]
        assert log_obj.request_id == "r2"
        assert log_obj.skill_name == "database"
        assert log_obj.error_code == "12001"
        assert log_obj.extra_data == {"key": "val"}


@pytest.mark.asyncio
async def test_write_audit_log_异常不崩溃():
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_ctx):
        from platform_mcp.audit.logger import write_audit_log
        with pytest.raises(Exception, match="DB down"):
            await write_audit_log(operator="admin")
