"""分组管理 API 集成测试 — 数据源组 + 服务器组 + 用户-组关联"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDatasourceGroupAPI:
    """数据源组 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_list_datasource_groups(self, admin_client, mock_db):
        """列出数据源组应返回分页数据"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/datasources")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "items" in body.get("data", {})

    @pytest.mark.asyncio
    async def test_create_datasource_group(self, admin_client, mock_db):
        """创建数据源组应成功"""
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/groups/datasources", json={
            "group_name": "DEV数据源组",
            "description": "开发环境数据源",
            "env_code": "DEV",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_datasource_group_nonexistent(self, admin_client, mock_db):
        """更新不存在的组应返回 14001"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/datasources/9999", json={
            "group_name": "updated",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 14001

    @pytest.mark.asyncio
    async def test_delete_datasource_group_nonexistent(self, admin_client, mock_db):
        """删除不存在的组应返回 14001"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/datasources/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 14001

    @pytest.mark.asyncio
    async def test_set_datasource_group_members(self, admin_client, mock_db):
        """设置数据源组成员"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/datasources/1/members", json={"ids": [1, 2]})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_datasource_group_members(self, admin_client, mock_db):
        """获取数据源组成员"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        resp = await admin_client.get("/api/v1/groups/datasources/1/members")
        assert resp.status_code == 200


class TestServerGroupAPI:
    """服务器组 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_list_server_groups(self, admin_client, mock_db):
        """列出服务器组应返回分页数据"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/servers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_create_server_group(self, admin_client, mock_db):
        """创建服务器组应成功"""
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/groups/servers", json={
            "group_name": "DEV服务器组",
            "description": "开发环境服务器",
            "env_code": "DEV",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_server_group_nonexistent(self, admin_client, mock_db):
        """更新不存在的组应返回 14002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/servers/9999", json={
            "group_name": "updated",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 14002

    @pytest.mark.asyncio
    async def test_delete_server_group_nonexistent(self, admin_client, mock_db):
        """删除不存在的组应返回 14002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/servers/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 14002

    @pytest.mark.asyncio
    async def test_set_server_group_members(self, admin_client, mock_db):
        """设置服务器组成员"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/servers/1/members", json={"ids": [1]})
        assert resp.status_code == 200


class TestUserGroupAPI:
    """用户-组关联 API 测试"""

    @pytest.mark.asyncio
    async def test_assign_user_groups(self, admin_client, mock_db):
        """分配用户到数据源组"""
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/users/2", json={
            "group_type": "datasource",
            "group_ids": [1, 2],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_user_groups(self, admin_client, mock_db):
        """获取用户的组关联"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        resp = await admin_client.get("/api/v1/groups/users/1")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert "datasource_groups" in data
        assert "server_groups" in data


class TestSystemConfigAPI:
    """系统配置 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_list_system_configs(self, admin_client, mock_db):
        """列出系统配置"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/system-config")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_create_system_config(self, admin_client, mock_db):
        """创建系统配置"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "test.key",
            "config_value": "test_value",
            "config_type": "string",
            "description": "测试配置",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_system_config_nonexistent(self, admin_client, mock_db):
        """更新不存在的配置应返回 16002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/system-config/9999", json={
            "config_value": "updated",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 16002

    @pytest.mark.asyncio
    async def test_delete_system_config_nonexistent(self, admin_client, mock_db):
        """删除不存在的配置应返回 16002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 16002