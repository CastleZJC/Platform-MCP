"""5.4.4 审计日志查询并发测试 — 20 并发"""

import asyncio
import time

import pytest


class TestAuditPerformance:
    @pytest.mark.asyncio
    async def test_20_concurrent_audit_queries(self, admin_client):
        latencies = []

        async def do_query():
            start = time.monotonic()
            await admin_client.get("/api/v1/audit/logs")
            latencies.append((time.monotonic() - start) * 1000)

        await asyncio.gather(*[do_query() for _ in range(20)])
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        assert p95 < 1000, f"P95 latency {p95}ms exceeds 1000ms"
