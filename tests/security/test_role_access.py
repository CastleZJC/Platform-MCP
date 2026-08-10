"""5.2.3 权限校验测试 — admin/developer 双角色"""

import pytest


class TestRoleAccess:
    @pytest.mark.asyncio
    async def test_developer_cannot_encrypt(self, dev_client):
        resp = await dev_client.post("/api/v1/crypto/encrypt", json={"plaintext": "test"})
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_developer_cannot_list_users(self, dev_client):
        resp = await dev_client.get("/api/v1/users")
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_developer_cannot_update_skill_status(self, dev_client):
        resp = await dev_client.put("/api/v1/skills/1/status", json={"status": "DISABLED"})
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_developer_can_list_datasources(self, dev_client):
        resp = await dev_client.get("/api/v1/datasources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_access_all(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources")
        assert resp.status_code == 200
