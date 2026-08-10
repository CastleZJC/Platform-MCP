"""5.1.6 API 集成测试 — 认证接口"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from platform_mcp.auth.session import SessionManager
from platform_mcp.common.database import get_db


class TestAuthAPI:
    @pytest.mark.asyncio
    async def test_login_success(self):
        local_sm = SessionManager()
        from platform_mcp.main import app
        async def override_db():
            yield AsyncMock()
        app.dependency_overrides[get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("platform_mcp.api.auth.session_manager", local_sm), \
                 patch("platform_mcp.api.auth.authenticate_user", return_value={
                     "id": 1, "username": "admin", "nickname": "管理员", "role_code": "admin", "status": 1,
                 }):
                resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["username"] == "admin"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self):
        local_sm = SessionManager()
        from platform_mcp.main import app
        async def override_db():
            yield AsyncMock()
        app.dependency_overrides[get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("platform_mcp.api.auth.session_manager", local_sm), \
                 patch("platform_mcp.api.auth.authenticate_user", return_value=None):
                resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        app.dependency_overrides.clear()
        data = resp.json()
        assert data["code"] == 11001

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self):
        local_sm = SessionManager()
        sid = local_sm.create(1, "admin", "管理员", "admin")
        from platform_mcp.main import app
        async def override_db():
            yield AsyncMock()
        app.dependency_overrides[get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("platform_mcp.api.auth.session_manager", local_sm):
                resp = await client.post("/api/v1/auth/logout", cookies={"session_id": sid})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert local_sm.get(sid) is None

    @pytest.mark.asyncio
    async def test_me_valid_session(self, admin_client):
        resp = await admin_client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["username"] == "admin"

    @pytest.mark.asyncio
    async def test_me_returns_user_info(self, admin_client):
        resp = await admin_client.get("/api/v1/auth/me")
        data = resp.json()
        assert data["data"]["role_code"] == "admin"
