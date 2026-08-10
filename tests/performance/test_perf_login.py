"""5.4.1 登录接口并发测试 — 50 并发"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from platform_mcp.auth.session import SessionManager
from platform_mcp.common.database import get_db


@pytest.fixture
async def client():
    from platform_mcp.main import app
    async def override_get_db():
        yield AsyncMock()
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestLoginPerformance:
    @pytest.mark.asyncio
    async def test_50_concurrent_logins(self, client):
        local_sm = SessionManager()
        latencies = []

        async def do_login(i):
            start = time.monotonic()
            with patch("platform_mcp.api.auth.session_manager", local_sm), \
                 patch("platform_mcp.api.auth.authenticate_user", return_value={
                     "id": i, "username": f"user_{i}", "nickname": None, "role_code": "admin", "status": 1,
                 }):
                await client.post("/api/v1/auth/login", json={"username": f"user_{i}", "password": "pass"})
            latencies.append((time.monotonic() - start) * 1000)

        await asyncio.gather(*[do_login(i) for i in range(50)])
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        assert p95 < 1000, f"P95 latency {p95}ms exceeds 1000ms"
        assert len(latencies) == 50
