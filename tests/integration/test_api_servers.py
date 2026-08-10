"""API 集成测试 — 服务器管理（镜像 test_api_datasources.py）"""

from unittest.mock import AsyncMock, patch

import pytest


class TestServersAPI:
    @pytest.mark.asyncio
    async def test_list_servers_admin(self, admin_client):
        resp = await admin_client.get("/api/v1/servers")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_list_servers_developer(self, dev_client):
        resp = await dev_client.get("/api/v1/servers")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_list_with_search(self, admin_client):
        resp = await admin_client.get("/api/v1/servers", params={"search": "176"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_with_env_filter(self, admin_client):
        resp = await admin_client.get("/api/v1/servers", params={"env_code": "DEV"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, admin_client):
        resp = await admin_client.get("/api/v1/servers", params={"status": 1})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_developer_cannot_create(self, dev_client):
        resp = await dev_client.post("/api/v1/servers", json={
            "server_code": "s1", "server_name": "S1",
            "host": "127.0.0.1", "ssh_port": 22, "username": "u",
            "env_code": "DEV", "encrypted_password": "AES:xxx",
        })
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_create_requires_credential(self, admin_client):
        resp = await admin_client.post("/api/v1/servers", json={
            "server_code": "s2", "server_name": "S2",
            "host": "127.0.0.1", "ssh_port": 22, "username": "u",
            "env_code": "DEV",
        })
        assert resp.json()["code"] == 13002

    @pytest.mark.asyncio
    async def test_test_connection_endpoint(self, admin_client):
        with patch(
            "platform_mcp.api.servers.server_manager.test_connection",
            new_callable=AsyncMock,
            return_value={"success": True, "latency_ms": 10, "echo": "Platform-MCP-ok"},
        ):
            resp = await admin_client.post("/api/v1/servers/1/test")
        assert resp.json()["code"] in (0, 13003)

    @pytest.mark.asyncio
    async def test_status_update_nonexistent(self, admin_client):
        resp = await admin_client.put("/api/v1/servers/999999/status", json={"status": 0})
        assert resp.json()["code"] == 13003

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, admin_client):
        resp = await admin_client.put("/api/v1/servers/999999", json={"remark": "x"})
        assert resp.json()["code"] == 13003
