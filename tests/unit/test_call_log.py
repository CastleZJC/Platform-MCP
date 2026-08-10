"""MCP 调用日志单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.mcp_server.context import McpContext


def _make_context():
    return McpContext(
        tool_name="execute_sql_text",
        operator="admin",
        skill_name="database",
        target_datasource="ds1",
        target_env="DEV",
        trace_id="t1",
        request_id="r1",
    )


@pytest.mark.asyncio
async def test_log_mcp_call_正常记录():
    ctx = _make_context()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_sess_ctx = MagicMock()
    mock_sess_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_sess_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_sess_ctx), \
         patch("platform_mcp.audit.logger.write_audit_log", new_callable=AsyncMock):
        from platform_mcp.mcp_server.call_log import log_mcp_call
        await log_mcp_call(ctx, "success", 150)
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

        log_obj = mock_session.add.call_args[0][0]
        assert log_obj.tool_name == "execute_sql_text"
        assert log_obj.caller == "admin"
        assert log_obj.trace_id == "t1"
        assert log_obj.env_code == "DEV"
        assert log_obj.result_status == "success"
        assert log_obj.duration_ms == 150
        assert log_obj.error_message is None


@pytest.mark.asyncio
async def test_log_mcp_call_异常时warning():
    ctx = _make_context()

    mock_sess_ctx = MagicMock()
    mock_sess_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB error"))
    mock_sess_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_sess_ctx), \
         patch("platform_mcp.mcp_server.call_log.logger") as mock_logger:
        from platform_mcp.mcp_server.call_log import log_mcp_call
        await log_mcp_call(ctx, "error", 50, error="timeout")
        mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_log_mcp_call_透传审计扩展字段():
    """验证 risk_level / request_summary / extra_data 从 ctx 透传到 write_audit_log。"""
    ctx = _make_context()
    ctx.risk_level = "HIGH"
    ctx.request_summary = "tool=execute_sql_text sql=DROP TABLE pmcp_test"
    ctx.extra_data = {"confirm_token": "tok_abc", "statement_type": "DROP"}

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_sess_ctx = MagicMock()
    mock_sess_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_sess_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=mock_sess_ctx), \
         patch("platform_mcp.audit.logger.write_audit_log", new_callable=AsyncMock) as mock_write:
        from platform_mcp.mcp_server.call_log import log_mcp_call
        await log_mcp_call(ctx, "success", 80)
        kwargs = mock_write.call_args.kwargs
        assert kwargs.get("risk_level") == "HIGH"
        assert kwargs.get("extra_data") == {"confirm_token": "tok_abc", "statement_type": "DROP"}
        assert "DROP TABLE pmcp_test" in kwargs.get("request_summary", "")
