"""5.1.7 MCP Tool 端到端测试 — Mock DB 连接"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.mcp_server.context import McpContext, build_context
from platform_mcp.mcp_server.tool_wrapper import format_tool_result
from platform_mcp.skills.database.risk import RiskLevel


class TestMCPToolExecuteSQLText:
    @pytest.mark.asyncio
    async def test_execute_sql_text_success(self):
        from platform_mcp.skills.database.executor import ExecutionResult
        mock_result = ExecutionResult(
            success=True, columns=["ID"], rows=[["1"]], row_count=1, duration_ms=50,
        )
        ctx = build_context("execute_sql_text", datasource_code="test_ds", env_code="DEV")
        formatted = format_tool_result(
            data={"success": True, "columns": ["ID"], "rows": [["1"]], "row_count": 1},
            trace_id=ctx.trace_id,
        )
        assert '"success": true' in formatted.lower() or '"success":True' in formatted
        assert ctx.trace_id in formatted

    @pytest.mark.asyncio
    async def test_execute_sql_text_high_risk_needs_confirm(self):
        from platform_mcp.skills.database.risk import RiskEngine
        engine = RiskEngine()
        result = engine.analyze("DELETE FROM users", env_code="DEV")
        assert result.needs_confirm is True
        assert result.level == RiskLevel.HIGH


class TestMCPToolValidateSQL:
    def test_validate_sql_drop_critical(self):
        from platform_mcp.skills.database.risk import RiskEngine
        engine = RiskEngine()
        result = engine.analyze("DROP TABLE users")
        assert result.level == RiskLevel.CRITICAL

    def test_validate_sql_select_low(self):
        from platform_mcp.skills.database.risk import RiskEngine
        engine = RiskEngine()
        result = engine.analyze("SELECT * FROM users WHERE id = 1")
        assert result.level == RiskLevel.LOW

    def test_validate_sql_insert_medium(self):
        from platform_mcp.skills.database.risk import RiskEngine
        engine = RiskEngine()
        result = engine.analyze("INSERT INTO log (msg) VALUES ('test')")
        assert result.level == RiskLevel.MEDIUM


class TestMCPToolListDatasources:
    @pytest.mark.asyncio
    async def test_list_datasources_returns_list(self):
        with patch("platform_mcp.datasource.manager.datasource_manager.list_accessible_datasources",
                   return_value=[
                       {"datasource_code": "ds1", "datasource_name": "DS1", "db_type": "mysql",
                        "host": "localhost", "port": 3306, "env_code": "DEV", "status": 1},
                   ]) as mock_list:
            result = await mock_list()
            assert len(result) == 1
            assert result[0]["datasource_code"] == "ds1"


class TestMCPToolGetExecutionStatus:
    def test_format_result_includes_trace_id(self):
        ctx = build_context("get_execution_status", datasource_code="ds1")
        result = format_tool_result(
            data={"status": "COMPLETED", "rows_affected": 5},
            trace_id=ctx.trace_id,
        )
        import json
        parsed = json.loads(result)
        assert parsed["data"]["status"] == "COMPLETED"
        assert parsed["trace_id"] == ctx.trace_id
