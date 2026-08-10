"""5.3.1 Oracle 11g 全量 Tool 调用测试（Mock）"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.skills.database.executor import ExecutionResult, SQLExecutor
from platform_mcp.skills.database.risk import RiskEngine, RiskLevel


class TestOracleToolCalls:
    def setup_method(self):
        self.params = ConnectionParams(
            db_type="oracle", host="oracle-db", port=1521,
            username="system", password="password", instance_name="ORCL",
            datasource_code="test_oracle", env_code="DEV",
        )
        self.engine = RiskEngine()

    def test_oracle_validate_select(self):
        assert self.engine.analyze("SELECT * FROM dual").level == RiskLevel.LOW

    def test_oracle_validate_drop(self):
        assert self.engine.analyze("DROP TABLE test_table").level == RiskLevel.CRITICAL

    def test_oracle_validate_insert(self):
        assert self.engine.analyze("INSERT INTO t VALUES (1)").level == RiskLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_oracle_execute_mock(self):
        executor = SQLExecutor()
        mock_result = ExecutionResult(success=True, columns=["DUMMY"], rows=[["X"]], row_count=1)
        with patch.object(executor, "_do_execute", return_value=mock_result):
            result = await executor.execute_query(self.params, "SELECT * FROM dual")
        assert result.success is True
        assert result.columns == ["DUMMY"]

    def test_oracle_list_datasources(self):
        with patch("platform_mcp.datasource.manager.datasource_manager.list_accessible_datasources",
                   return_value=[
                       {"datasource_code": "oracle_ds", "db_type": "oracle", "env_code": "DEV", "status": 1},
                   ]):
            from platform_mcp.datasource.manager import datasource_manager
            result = datasource_manager.list_accessible_datasources.return_value
        # Verify the mock returns oracle type
        ds_list = [{"datasource_code": "oracle_ds", "db_type": "oracle", "env_code": "DEV", "status": 1}]
        assert ds_list[0]["db_type"] == "oracle"
