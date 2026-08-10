"""5.1.6 API 集成测试 — 用户管理"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestUsersAPI:
    @pytest.mark.asyncio
    async def test_list_users(self, admin_client):
        resp = await admin_client.get("/api/v1/users")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_user(self, admin_client):
        with patch("platform_mcp.api.users.hash_password", return_value="$2b$12$hashed"):
            resp = await admin_client.post("/api/v1/users", json={
                "username": "newuser", "password": "pass123", "nickname": "新用户", "role_code": "developer",
            })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_developer_cannot_access_users(self, dev_client):
        resp = await dev_client.get("/api/v1/users")
        assert resp.status_code == 400
        data = resp.json()
        assert data["code"] == 11001

    @pytest.mark.asyncio
    async def test_update_user_status(self, admin_client):
        resp = await admin_client.put("/api/v1/users/2/status", json={"status": 0})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_users_带search过滤(self, admin_client):
        resp = await admin_client.get("/api/v1/users", params={"search": "admin"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_user_用户名重复_返回11002(self, admin_client):
        resp = await admin_client.post("/api/v1/users", json={
            "username": "admin", "password": "pass", "nickname": "重复", "role_code": "admin",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_user_不存在(self, admin_client):
        resp = await admin_client.put("/api/v1/users/9999", json={"nickname": "新昵称"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_user_status_不存在(self, admin_client):
        resp = await admin_client.put("/api/v1/users/9999/status", json={"status": 0})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_不存在(self, admin_client):
        with patch("platform_mcp.api.users.hash_password", return_value="$2b$12$h"):
            resp = await admin_client.post("/api/v1/users/9999/reset-password", json={"new_password": "new123"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_user_含role_code(self, admin_client, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.nickname = "old"
        mock_db.get = AsyncMock(return_value=mock_user)
        resp = await admin_client.put("/api/v1/users/1", json={"nickname": "新昵", "role_code": "admin"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_存在(self, admin_client, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_db.get = AsyncMock(return_value=mock_user)
        with patch("platform_mcp.api.users.hash_password", return_value="$2b$12$new"):
            resp = await admin_client.post("/api/v1/users/1/reset-password", json={"new_password": "new123"})
        assert resp.status_code == 200
