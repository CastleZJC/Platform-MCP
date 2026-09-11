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
    async def test_developer_skill_status_not_admin_gated(self, dev_client):
        """批次 6.3：个人 Skill 启停放宽 owner-or-admin——dev 请求过角色门进业务逻辑（非 11001）。"""
        resp = await dev_client.put("/api/v1/skills/1/status", json={"status": "DISABLED"})
        assert resp.json()["code"] == 10002  # 角色 gate 已移除，不存在 Skill 走 10002

    @pytest.mark.asyncio
    async def test_developer_can_list_datasources(self, dev_client):
        resp = await dev_client.get("/api/v1/datasources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_access_all(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources")
        assert resp.status_code == 200
