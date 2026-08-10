"""5.3.2 MySQL 5.6 全量 Tool 调用测试（Mock）"""

from unittest.mock import patch

import pytest

from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.skills.database.executor import ExecutionResult, SQLExecutor
from platform_mcp.skills.database.risk import RiskEngine, RiskLevel


class TestMySQLToolCalls:
    def setup_method(self):
        self.params = ConnectionParams(
            db_type="mysql", host="mysql-db", port=3306,
            username="root", password="password", database="testdb",
            datasource_code="test_mysql", env_code="DEV",
        )
        self.engine = RiskEngine()

    def test_mysql_validate_select(self):
        assert self.engine.analyze("SELECT 1").level == RiskLevel.LOW

    def test_mysql_validate_insert(self):
        assert self.engine.analyze("INSERT INTO users (name) VALUES ('test')").level == RiskLevel.MEDIUM

    def test_mysql_validate_delete_with_where(self):
        assert self.engine.analyze("DELETE FROM t WHERE 1=1").level == RiskLevel.MEDIUM

    def test_mysql_validate_delete_no_where(self):
        assert self.engine.analyze("DELETE FROM t").level == RiskLevel.HIGH

    def test_mysql_validate_drop(self):
        assert self.engine.analyze("DROP TABLE t").level == RiskLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_mysql_execute_mock(self):
        executor = SQLExecutor()
        mock_result = ExecutionResult(success=True, columns=["1"], rows=[["1"]], row_count=1)
        with patch.object(executor, "_do_execute", return_value=mock_result):
            result = await executor.execute_query(self.params, "SELECT 1")
        assert result.success is True
