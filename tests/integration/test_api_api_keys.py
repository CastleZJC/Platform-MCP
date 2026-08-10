"""5.1.4 API 集成测试 — API Key 管理（双存储）

P0-1: 覆盖 API Key 全套 endpoint：
- POST /api-keys 生成（返回 raw_key + key_prefix）
- GET /api-keys 列表（仅 key_prefix）
- DELETE /api-keys/{id} 撤销
- POST /api-keys/{id}/regenerate 重置
- POST /api-keys/reset/{user_id} admin 重置
- GET /api-keys/full/{user_id} admin reveal 明文（self-or-admin）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestApiKeysAPI:
    """API Key 管理 endpoints"""

    @pytest.mark.asyncio
    async def test_create_key_returns_raw_key_and_prefix(self, admin_client):
        """POST /api-keys 生成新 key，返回 raw_key + key_prefix"""
        with patch("platform_mcp.api.api_keys.generate_api_key", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "pmcp_abcdefghijklmnop1234567890"
            resp = await admin_client.post("/api/v1/api-keys", json={"description": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["key"] == "pmcp_abcdefghijklmnop1234567890"
        assert "key_prefix" in body["data"]
        assert "****" in body["data"]["key_prefix"]

    @pytest.mark.asyncio
    async def test_create_key_calls_generate_and_commit(self, admin_client, mock_db):
        """生成 key 时调用 generate_api_key 服务并 commit"""
        with patch("platform_mcp.api.api_keys.generate_api_key", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "pmcp_test_key"
            await admin_client.post("/api/v1/api-keys", json={"description": "test"})
        mock_gen.assert_awaited_once()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_keys_returns_only_prefix(self, admin_client):
        """GET /api-keys 列表不含完整 key"""
        with patch("platform_mcp.api.api_keys.list_user_keys", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [
                {"id": 1, "key_prefix": "pmcp_abcd", "description": "k1", "status": 1},
                {"id": 2, "key_prefix": "pmcp_efgh", "description": "k2", "status": 0},
            ]
            resp = await admin_client.get("/api/v1/api-keys")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        for item in body["data"]:
            assert "key" not in item
            assert "key_prefix" in item

    @pytest.mark.asyncio
    async def test_delete_key_success(self, admin_client):
        """DELETE /api-keys/{id} 撤销成功"""
        with patch("platform_mcp.api.api_keys.revoke_api_key", new_callable=AsyncMock) as mock_revoke:
            mock_revoke.return_value = True
            resp = await admin_client.delete("/api/v1/api-keys/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_key_not_exist_returns_code_1(self, admin_client):
        """撤销不存在的 key：返回 code=1"""
        with patch("platform_mcp.api.api_keys.revoke_api_key", new_callable=AsyncMock) as mock_revoke:
            mock_revoke.return_value = False
            resp = await admin_client.delete("/api/v1/api-keys/999")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1

    @pytest.mark.asyncio
    async def test_regenerate_key_returns_new_raw(self, admin_client):
        """POST /api-keys/{id}/regenerate 重置返回新 raw_key"""
        with patch("platform_mcp.api.api_keys.regenerate_api_key", new_callable=AsyncMock) as mock_regen:
            mock_regen.return_value = "pmcp_new_key_xyz_1234567890"
            resp = await admin_client.post("/api/v1/api-keys/1/regenerate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["key"] == "pmcp_new_key_xyz_1234567890"

    @pytest.mark.asyncio
    async def test_regenerate_key_not_exist_returns_code_1(self, admin_client):
        with patch("platform_mcp.api.api_keys.regenerate_api_key", new_callable=AsyncMock) as mock_regen:
            mock_regen.return_value = None
            resp = await admin_client.post("/api/v1/api-keys/999/regenerate")
        assert resp.json()["code"] == 1

    @pytest.mark.asyncio
    async def test_admin_reset_user_key(self, admin_client):
        """POST /api-keys/reset/{user_id} admin 重置用户 key"""
        with patch("platform_mcp.api.api_keys.generate_api_key", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "pmcp_reset_new_key_1234567890"
            resp = await admin_client.post("/api/v1/api-keys/reset/5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["key"] == "pmcp_reset_new_key_1234567890"

    @pytest.mark.asyncio
    async def test_admin_reset_revokes_all_active_keys(self, admin_client, mock_db):
        """admin reset 时先执行 UPDATE 撤销所有活跃 key，再生成新 key"""
        with patch("platform_mcp.api.api_keys.generate_api_key", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "pmcp_new"
            await admin_client.post("/api/v1/api-keys/reset/5")
        mock_db.execute.assert_awaited()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_developer_cannot_reset_others_key(self, dev_client):
        """developer 角色不能调用 admin reset endpoint — AuthError 被全局 handler 处理为 400"""
        resp = await dev_client.post("/api/v1/api-keys/reset/5")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] != 0  # 非 0 表示业务错误

    @pytest.mark.asyncio
    async def test_admin_reveal_any_user_plaintext(self, admin_client):
        """GET /api-keys/full/{user_id} admin 可查任意用户明文"""
        with patch("platform_mcp.api.api_keys.get_full_key_by_user", new_callable=AsyncMock) as mock_reveal:
            mock_reveal.return_value = "pmcp_revealed_plaintext_key"
            resp = await admin_client.get("/api/v1/api-keys/full/5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["key"] == "pmcp_revealed_plaintext_key"

    @pytest.mark.asyncio
    async def test_user_reveal_own_key_success(self, dev_client, developer_user):
        """普通用户 reveal 自己的 key 成功"""
        user_id = developer_user["id"]
        with patch("platform_mcp.api.api_keys.get_full_key_by_user", new_callable=AsyncMock) as mock_reveal:
            mock_reveal.return_value = "pmcp_dev_own_key"
            resp = await dev_client.get(f"/api/v1/api-keys/full/{user_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["key"] == "pmcp_dev_own_key"

    @pytest.mark.asyncio
    async def test_user_reveal_others_key_forbidden(self, dev_client):
        """普通用户 reveal 他人 key：AuthError 被全局 handler 处理为 400"""
        with patch("platform_mcp.api.api_keys.get_full_key_by_user", new_callable=AsyncMock) as mock_reveal:
            mock_reveal.return_value = "pmcp_others_key"
            resp = await dev_client.get("/api/v1/api-keys/full/999")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] != 0

    @pytest.mark.asyncio
    async def test_reveal_hash_only_returns_code_1(self, admin_client):
        """hash-only 历史 key reveal 返回 code=1 + 提示 reset"""
        with patch("platform_mcp.api.api_keys.get_full_key_by_user", new_callable=AsyncMock) as mock_reveal:
            mock_reveal.return_value = None
            resp = await admin_client.get("/api/v1/api-keys/full/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert "reset" in body["message"].lower() or "重置" in body["message"]

    @pytest.mark.asyncio
    async def test_create_key_writes_audit_log(self, admin_client):
        """生成 key 时写审计日志（resource_type=permission）"""
        with patch("platform_mcp.api.api_keys.generate_api_key", new_callable=AsyncMock) as mock_gen, \
             patch("platform_mcp.api.api_keys.write_audit_log", new_callable=AsyncMock) as mock_audit:
            mock_gen.return_value = "pmcp_test_key"
            await admin_client.post("/api/v1/api-keys", json={"description": "test"})
        mock_audit.assert_awaited()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["resource_type"] == "permission"
        assert audit_kwargs["result_status"] == "success"
        assert "key_prefix" in audit_kwargs["extra_data"]

    @pytest.mark.asyncio
    async def test_delete_key_writes_audit_log(self, admin_client):
        """撤销 key 时写审计日志"""
        with patch("platform_mcp.api.api_keys.revoke_api_key", new_callable=AsyncMock) as mock_revoke, \
             patch("platform_mcp.api.api_keys.write_audit_log", new_callable=AsyncMock) as mock_audit:
            mock_revoke.return_value = True
            await admin_client.delete("/api/v1/api-keys/1")
        mock_audit.assert_awaited()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["resource_type"] == "permission"
        assert audit_kwargs["resource_id"] == "1"

    @pytest.mark.asyncio
    async def test_admin_reset_writes_audit_log(self, admin_client):
        """admin reset 时写审计日志"""
        with patch("platform_mcp.api.api_keys.generate_api_key", new_callable=AsyncMock) as mock_gen, \
             patch("platform_mcp.api.api_keys.write_audit_log", new_callable=AsyncMock) as mock_audit:
            mock_gen.return_value = "pmcp_new"
            await admin_client.post("/api/v1/api-keys/reset/5")
        mock_audit.assert_awaited()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["resource_type"] == "permission"
        assert audit_kwargs["resource_id"] == "5"
        assert audit_kwargs["extra_data"]["target_user_id"] == 5

    @pytest.mark.asyncio
    async def test_reveal_writes_audit_log(self, admin_client):
        """reveal 明文时写审计日志（高敏感操作）"""
        with patch("platform_mcp.api.api_keys.get_full_key_by_user", new_callable=AsyncMock) as mock_reveal, \
             patch("platform_mcp.api.api_keys.write_audit_log", new_callable=AsyncMock) as mock_audit:
            mock_reveal.return_value = "pmcp_revealed"
            await admin_client.get("/api/v1/api-keys/full/5")
        mock_audit.assert_awaited()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["resource_type"] == "permission"
        assert audit_kwargs["extra_data"]["target_user_id"] == 5
        assert audit_kwargs["extra_data"]["revealed_by"] == "admin"
