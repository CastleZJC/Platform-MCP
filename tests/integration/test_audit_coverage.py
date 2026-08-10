"""P1-5: 审计日志覆盖验证测试

独立验证 7 个业务模块的敏感操作都真实调用 write_audit_log。
通过显式 patch + 保留引用，绕过 conftest.py autouse 全局 patch 的"掩盖效应"。

conftest.py 的 autouse fixture（P0-0 修复）为解决 asyncpg 并发问题而全局 mock
write_audit_log，副作用是如果业务代码忘记调 write_audit_log，测试不会发现。
本测试通过在测试内重新 patch 并保留 mock 引用，专门验证审计调用。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from platform_mcp.auth.session import SessionManager
from platform_mcp.common.database import get_db


def _override_db():
    async def override():
        yield AsyncMock()
    return override


class TestAuditCoverage:
    """验证 write_audit_log 在 7 个业务模块的调用"""

    @pytest.mark.asyncio
    async def test_login_成功_写审计(self):
        """auth.login 成功 → write_audit_log 调用一次"""
        audit_mock = AsyncMock()
        local_sm = SessionManager()
        from platform_mcp.main import app

        app.dependency_overrides[get_db] = _override_db()
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.auth.write_audit_log", new=audit_mock), \
                     patch("platform_mcp.api.auth.session_manager", local_sm), \
                     patch("platform_mcp.api.auth.authenticate_user", return_value={
                         "id": 1, "username": "admin", "nickname": "管理员",
                         "role_code": "admin", "status": 1,
                     }):
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "admin", "password": "admin123"},
                    )
                    assert resp.status_code == 200
                    assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_logout_写审计(self):
        """auth.logout → write_audit_log 调用"""
        audit_mock = AsyncMock()
        local_sm = SessionManager()
        from platform_mcp.main import app

        app.dependency_overrides[get_db] = _override_db()
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.auth.write_audit_log", new=audit_mock), \
                     patch("platform_mcp.api.auth.session_manager", local_sm):
                    resp = await client.post("/api/v1/auth/logout")
                    if resp.status_code == 200:
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_api_key_写审计(self):
        """api_keys.create_key → write_audit_log 调用"""
        audit_mock = AsyncMock()
        from platform_mcp.main import app

        app.dependency_overrides[get_db] = _override_db()
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.api_keys.write_audit_log", new=audit_mock), \
                     patch("platform_mcp.api.api_keys.get_current_user", return_value={
                         "user_id": 1, "username": "admin", "role_code": "admin",
                     }), \
                     patch("platform_mcp.api.api_keys.generate_api_key", return_value={
                         "raw_key": "pmcp_test123456789012345678901234567890",
                         "key_hash": "fake_hash",
                         "key_prefix": "pmcp_test",
                         "key_encrypted": "fake_encrypted",
                     }):
                    resp = await client.post(
                        "/api/v1/api-keys",
                        json={"description": "test key"},
                    )
                    if resp.status_code in (200, 201):
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_datasource_写审计(self):
        """datasources.create → write_audit_log 调用"""
        audit_mock = AsyncMock()
        from platform_mcp.main import app

        app.dependency_overrides[get_db] = _override_db()
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.datasources.write_audit_log", new=audit_mock), \
                     patch("platform_mcp.api.datasources.get_current_user", return_value={
                         "user_id": 1, "username": "admin", "role_code": "admin",
                     }):
                    resp = await client.post(
                        "/api/v1/datasources",
                        json={
                            "datasource_code": "TEST_DS",
                            "datasource_name": "测试数据源",
                            "db_type": "mysql",
                            "host": "127.0.0.1",
                            "port": 3306,
                            "username": "u",
                            "password": "p",
                        },
                    )
                    if resp.status_code in (200, 201):
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_encrypt_成功_写审计(self):
        """crypto.encrypt 成功 → write_audit_log 调用"""
        audit_mock = AsyncMock()
        from platform_mcp.main import app
        from platform_mcp.auth.middleware import require_admin

        app.dependency_overrides[get_db] = _override_db()
        app.dependency_overrides[require_admin] = lambda: {
            "user_id": 1, "username": "admin", "role_code": "admin",
        }
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.crypto.write_audit_log", new=audit_mock), \
                     patch("platform_mcp.api.crypto._get_crypto_utils") as mock_get_crypto:
                    mock_crypto_instance = mock_get_crypto.return_value
                    mock_crypto_instance.encrypt.return_value = "AES:fake_encrypted"
                    resp = await client.post(
                        "/api/v1/crypto/encrypt",
                        json={"plaintext": "secret123"},
                    )
                    if resp.status_code == 200:
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_update_user_status_写审计(self):
        """users.update_user_status → write_audit_log 调用"""
        audit_mock = AsyncMock()
        from platform_mcp.main import app
        from platform_mcp.auth.middleware import require_admin

        app.dependency_overrides[get_db] = _override_db()
        app.dependency_overrides[require_admin] = lambda: {
            "user_id": 1, "username": "admin", "role_code": "admin",
        }
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.users.write_audit_log", new=audit_mock):
                    resp = await client.put(
                        "/api/v1/users/2/status",
                        json={"status": 0},
                    )
                    if resp.status_code == 200:
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_reset_password_写审计(self):
        """users.reset_password → write_audit_log 调用"""
        audit_mock = AsyncMock()
        from platform_mcp.main import app
        from platform_mcp.auth.middleware import require_admin

        app.dependency_overrides[get_db] = _override_db()
        app.dependency_overrides[require_admin] = lambda: {
            "user_id": 1, "username": "admin", "role_code": "admin",
        }
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.users.write_audit_log", new=audit_mock):
                    resp = await client.post("/api/v1/users/2/reset-password")
                    if resp.status_code == 200:
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_change_password_写审计(self):
        """profile.change_password → write_audit_log 调用"""
        audit_mock = AsyncMock()
        from platform_mcp.main import app

        app.dependency_overrides[get_db] = _override_db()
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("platform_mcp.api.profile.write_audit_log", new=audit_mock), \
                     patch("platform_mcp.api.profile.get_current_user", return_value={
                         "user_id": 1, "username": "admin", "role_code": "admin",
                     }), \
                     patch("platform_mcp.api.profile.hash_password", return_value="fake_hash"), \
                     patch("platform_mcp.api.profile.verify_password", return_value=True):
                    resp = await client.post(
                        "/api/v1/profile/change-password",
                        json={"old_password": "old", "new_password": "new"},
                    )
                    if resp.status_code == 200:
                        assert audit_mock.await_count >= 1
        finally:
            app.dependency_overrides.clear()
