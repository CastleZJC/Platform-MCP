"""5.4.3 SQL 执行并发测试 — 10 并发"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.skills.database.executor import ExecutionResult, SQLExecutor
from platform_mcp.skills.database.risk import RiskEngine


class TestSQLExecPerformance:
    @pytest.mark.asyncio
    async def test_10_concurrent_risk_assessments(self):
        engine = RiskEngine()
        latencies = []

        async def assess():
            start = time.monotonic()
            engine.analyze("SELECT * FROM users WHERE id = 1")
            latencies.append((time.monotonic() - start) * 1000)

        await asyncio.gather(*[assess() for _ in range(10)])
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        assert p95 < 2000, f"P95 latency {p95}ms exceeds 2000ms"

    @pytest.mark.asyncio
    async def test_10_concurrent_mock_executions(self):
        executor = SQLExecutor()
        params = ConnectionParams(
            db_type="mysql", host="localhost", port=3306,
            username="root", password="", datasource_code="test",
        )
        mock_result = ExecutionResult(success=True, columns=["1"], rows=[["1"]], row_count=1)
        latencies = []

        async def execute():
            start = time.monotonic()
            with patch.object(executor, "_do_execute", return_value=mock_result):
                await executor.execute_query(params, "SELECT 1")
            latencies.append((time.monotonic() - start) * 1000)

        await asyncio.gather(*[execute() for _ in range(10)])
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        assert p95 < 3000, f"P95 latency {p95}ms exceeds 3000ms"
