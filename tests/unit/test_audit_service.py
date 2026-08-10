"""audit/service 单元测试 — query_logs / get_stats"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_query_logs_无过滤():
    mock_db = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 0
    mock_log_result = MagicMock()
    mock_log_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_log_result])

    from platform_mcp.audit.service import query_logs
    items, total = await query_logs(mock_db)
    assert total == 0
    assert items == []


@pytest.mark.asyncio
async def test_query_logs_有operator过滤():
    mock_db = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 5
    mock_log_result = MagicMock()
    mock_log_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_log_result])

    from platform_mcp.audit.service import query_logs
    items, total = await query_logs(mock_db, operator="admin")
    assert total == 5


@pytest.mark.asyncio
async def test_query_logs_多条件过滤():
    mock_db = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 1
    mock_log_result = MagicMock()
    mock_log_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_log_result])

    from platform_mcp.audit.service import query_logs
    items, total = await query_logs(
        mock_db, operator="dev01", skill_name="database",
        risk_level="HIGH", result_status="ERROR",
        start_time="2024-01-01", end_time="2024-12-31",
    )
    assert total == 1


@pytest.mark.asyncio
async def test_query_logs_有日志记录():
    mock_db = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 1

    mock_log = MagicMock()
    mock_log.id = 1
    mock_log.trace_id = "t1"
    mock_log.operator = "admin"
    mock_log.skill_name = "database"
    mock_log.tool_name = "execute_sql_text"
    mock_log.resource_type = "datasource"
    mock_log.resource_id = "ds1"
    mock_log.risk_level = "LOW"
    mock_log.result_status = "SUCCESS"
    mock_log.duration_ms = 100
    mock_log.error_message = None
    mock_log.inserted_at = None

    mock_log_result = MagicMock()
    mock_log_result.scalars.return_value.all.return_value = [mock_log]
    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_log_result])

    from platform_mcp.audit.service import query_logs
    items, total = await query_logs(mock_db)
    assert total == 1
    assert items[0]["operator"] == "admin"


@pytest.mark.asyncio
async def test_get_stats_无operator():
    mock_db = AsyncMock()
    mock_scalar = MagicMock()
    mock_scalar.scalar.return_value = 10
    mock_db.execute = AsyncMock(return_value=mock_scalar)

    from platform_mcp.audit.service import get_stats
    result = await get_stats(mock_db)
    assert result["total_operations"] == 10
    assert result["mcp_calls"] == 10
    assert result["sql_executions"] == 10
    assert result["high_risk_blocks"] == 10


@pytest.mark.asyncio
async def test_get_stats_有operator():
    mock_db = AsyncMock()
    mock_scalar = MagicMock()
    mock_scalar.scalar.return_value = 3
    mock_db.execute = AsyncMock(return_value=mock_scalar)

    from platform_mcp.audit.service import get_stats
    result = await get_stats(mock_db, operator="dev01")
    assert result["total_operations"] == 3
    assert "trends" in result
    assert mock_db.execute.call_count == 8
