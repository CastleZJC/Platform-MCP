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


class TestLoginSnapshot:
    """V3.0 M1：会话 TTL / 语言偏好登录时快照（重新登录生效，架构 §19.5.2）"""

    @staticmethod
    def _fake_runtime_config(timeout_minutes: int, default_locale: str):
        from types import SimpleNamespace

        async def fake_get(key: str):
            if key == "session.timeout_minutes":
                return timeout_minutes
            if key == "sys.default_locale":
                return default_locale
            if key == "sys.default_page_size":
                return 20
            raise KeyError(key)

        return SimpleNamespace(get=fake_get)

    async def _login_with(self, user: dict, timeout_minutes: int, default_locale: str):
        local_sm = SessionManager()
        from platform_mcp.main import app
        async def override_db():
            yield AsyncMock()
        app.dependency_overrides[get_db] = override_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("platform_mcp.api.auth.session_manager", local_sm), \
                 patch("platform_mcp.api.auth.authenticate_user", return_value=user), \
                 patch("platform_mcp.common.runtime_config.runtime_config",
                       self._fake_runtime_config(timeout_minutes, default_locale)):
                resp = await client.post("/api/v1/auth/login",
                                         json={"username": user["username"], "password": "x"})
        app.dependency_overrides.clear()
        return local_sm, resp

    @pytest.mark.asyncio
    async def test_login_snapshots_ttl_and_default_locale(self):
        user = {"id": 1, "username": "admin", "nickname": None, "role_code": "admin", "status": 1}
        local_sm, resp = await self._login_with(user, timeout_minutes=45, default_locale="en-US")
        assert resp.json()["code"] == 0
        assert "Max-Age=2700" in resp.headers.get("set-cookie", "")
        sid = resp.cookies.get("session_id")
        assert sid
        info = local_sm.get(sid)
        assert info is not None
        assert info.ttl_seconds == 45 * 60
        # 用户未设置语言偏好 → 回退运行时系统默认语言
        assert info.locale == "en-US"

    @pytest.mark.asyncio
    async def test_login_user_locale_wins_over_default(self):
        user = {"id": 2, "username": "dev", "nickname": None, "role_code": "developer",
                "status": 1, "locale": "zh-CN"}
        local_sm, resp = await self._login_with(user, timeout_minutes=45, default_locale="en-US")
        assert resp.json()["code"] == 0
        info = local_sm.get(resp.cookies.get("session_id"))
        assert info is not None
        assert info.locale == "zh-CN"
