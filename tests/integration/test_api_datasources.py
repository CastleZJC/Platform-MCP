"""5.1.6 API 集成测试 — 数据源管理"""

from unittest.mock import MagicMock, patch

import pytest


class TestDatasourcesAPI:
    @pytest.mark.asyncio
    async def test_list_datasources(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_developer_can_list_datasources(self, dev_client):
        resp = await dev_client.get("/api/v1/datasources")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_developer_cannot_create_datasource(self, dev_client):
        resp = await dev_client.post("/api/v1/datasources", json={
            "datasource_code": "ds1", "datasource_name": "DS1",
            "db_type": "mysql", "env_code": "DEV",
            "host": "localhost", "port": 3306, "username": "root",
        })
        data = resp.json()
        assert data["code"] == 11001

    @pytest.mark.asyncio
    async def test_list_datasources_带search过滤(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources", params={"search": "oracle"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_datasources_带db_type过滤(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources", params={"db_type": "mysql"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_datasources_带env_code过滤(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources", params={"env_code": "DEV"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_datasources_带status过滤(self, admin_client):
        resp = await admin_client.get("/api/v1/datasources", params={"status": 1})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_datasource_admin(self, admin_client):
        """测试 admin 创建数据源接口可达（深化断言：响应体字段）"""
        # 不再 mock PmcpDatasource.__init__（会破坏 ORM 字段访问）
        # 信任 fixture 已 mock db.add/commit，返回 200
        resp = await admin_client.post("/api/v1/datasources", json={
            "datasource_code": "ds2", "datasource_name": "DS2",
            "db_type": "mysql", "env_code": "DEV",
            "host": "localhost", "port": 3306, "username": "root",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "code" in data
        assert "message" in data

    @pytest.mark.asyncio
    async def test_update_datasource_status(self, admin_client):
        resp = await admin_client.put("/api/v1/datasources/1/status", json={"status": 0})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_datasource(self, admin_client):
        resp = await admin_client.put("/api/v1/datasources/1", json={"datasource_name": "更新名"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_test_connection_不存在(self, admin_client):
        resp = await admin_client.post("/api/v1/datasources/99999/test")
        assert resp.status_code == 200
        assert resp.json()["code"] == 12002

    @pytest.mark.asyncio
    async def test_create_rejects_empty_code(self, admin_client):
        """BUG20260814134000：空编码必须 422 拒绝，不得入库"""
        resp = await admin_client.post("/api/v1/datasources", json={
            "datasource_code": "", "datasource_name": "DS",
            "db_type": "mysql", "env_code": "DEV",
            "host": "localhost", "port": 3306, "username": "root",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_rejects_whitespace_code(self, admin_client):
        """BUG20260814134000：全空格编码同样 422 拒绝"""
        resp = await admin_client.post("/api/v1/datasources", json={
            "datasource_code": "   ", "datasource_name": "DS",
            "db_type": "mysql", "env_code": "DEV",
            "host": "localhost", "port": 3306, "username": "root",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_rejects_blank_required_fields(self, admin_client):
        """BUG20260814134000：其它 NOT NULL 必填字段空串同样拒绝"""
        resp = await admin_client.post("/api/v1/datasources", json={
            "datasource_code": "ds3", "datasource_name": "  ",
            "db_type": "mysql", "env_code": "DEV",
            "host": "localhost", "port": 3306, "username": "root",
        })
        assert resp.status_code == 422
