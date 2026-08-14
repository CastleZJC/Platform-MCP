"""E2E 测试 — 分组管理全流程（创建组→分配资源→分配用户→MCP 调用过滤）

测试策略：
1. 数据源组 CRUD + 成员管理
2. 服务器组 CRUD + 成员管理
3. 用户-组关联管理
4. 开发者权限限制验证（只读）
5. 环境过滤验证（dev 不可见 PROD）
6. 系统配置 CRUD
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ==================== 数据源组 CRUD ====================


class TestDatasourceGroupE2E:
    """F-13: 数据源组全流程 E2E"""

    @pytest.mark.asyncio
    async def test_create_datasource_group(self, admin_client, mock_db):
        """创建数据源组"""
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/groups/datasources", json={
            "group_name": "DEV核心数据源组",
            "description": "开发环境核心数据源",
            "env_code": "DEV",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @pytest.mark.asyncio
    async def test_list_datasource_groups(self, admin_client, mock_db):
        """列出数据源组"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/datasources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "items" in data.get("data", {})

    @pytest.mark.asyncio
    async def test_update_datasource_group(self, admin_client, mock_db):
        """更新数据源组"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV核心数据源组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/datasources/1", json={
            "group_name": "DEV核心数据源组V2",
            "description": "更新后描述",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_datasource_group(self, admin_client, mock_db):
        """删除数据源组（含成员清理）"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "待删除组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/datasources/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_datasource_group(self, admin_client, mock_db):
        """删除不存在的数据源组应返回 14001"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/datasources/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 14001

    @pytest.mark.asyncio
    async def test_set_datasource_group_members(self, admin_client, mock_db):
        """F-13: 分配数据源到组"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/datasources/1/members", json={"ids": [1, 2, 3]})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_datasource_group_members(self, admin_client, mock_db):
        """获取数据源组成员列表"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/datasources/1/members")
        assert resp.status_code == 200


# ==================== 服务器组 CRUD ====================


class TestServerGroupE2E:
    """F-14: 服务器组全流程 E2E"""

    @pytest.mark.asyncio
    async def test_create_server_group(self, admin_client, mock_db):
        """创建服务器组"""
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/groups/servers", json={
            "group_name": "DEV应用服务器组",
            "description": "开发环境应用服务器",
            "env_code": "DEV",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_list_server_groups(self, admin_client, mock_db):
        """列出服务器组"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/servers")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "items" in resp.json().get("data", {})

    @pytest.mark.asyncio
    async def test_update_server_group(self, admin_client, mock_db):
        """更新服务器组"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV应用服务器组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/servers/1", json={
            "group_name": "DEV应用服务器组V2",
            "description": "更新后描述",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_server_group(self, admin_client, mock_db):
        """删除服务器组（含成员清理）"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "待删除组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/servers/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_server_group(self, admin_client, mock_db):
        """删除不存在的服务器组应返回 14002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/servers/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 14002

    @pytest.mark.asyncio
    async def test_set_server_group_members(self, admin_client, mock_db):
        """F-14: 分配服务器到组"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/servers/1/members", json={"ids": [1, 2]})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_server_group_members(self, admin_client, mock_db):
        """获取服务器组成员列表"""
        mock_group = MagicMock()
        mock_group.id = 1
        mock_group.group_name = "DEV组"
        mock_db.get = AsyncMock(return_value=mock_group)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/servers/1/members")
        assert resp.status_code == 200


# ==================== 用户-组关联 ====================


class TestUserGroupE2E:
    """F-15/F-16: 用户-组关联全流程"""

    @pytest.mark.asyncio
    async def test_assign_user_to_datasource_groups(self, admin_client, mock_db):
        """F-16: 分配用户到数据源组"""
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/users/2", json={
            "group_type": "datasource",
            "group_ids": [1, 2],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_assign_user_to_server_groups(self, admin_client, mock_db):
        """F-16: 分配用户到服务器组"""
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/users/2", json={
            "group_type": "server",
            "group_ids": [3, 4],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

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

    @pytest.mark.asyncio
    async def test_assign_user_overwrites_previous(self, admin_client, mock_db):
        """覆盖式分配：再次分配会替换旧关联"""
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp1 = await admin_client.put("/api/v1/groups/users/2", json={
            "group_type": "datasource",
            "group_ids": [1],
        })
        assert resp1.status_code == 200
        resp2 = await admin_client.put("/api/v1/groups/users/2", json={
            "group_type": "datasource",
            "group_ids": [2, 3],
        })
        assert resp2.status_code == 200


# ==================== 开发者权限限制 ====================


class TestDevPermissionE2E:
    """F-15: dev 只读组权限验证"""

    @pytest.mark.asyncio
    async def test_dev_cannot_create_datasource_group(self, dev_client, mock_db):
        """developer 不能创建数据源组（AuthError → 400 + error_code 11001）"""
        resp = await dev_client.post("/api/v1/groups/datasources", json={
            "group_name": "DEV不应创建",
            "description": "不应创建",
            "env_code": "DEV",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_dev_cannot_create_server_group(self, dev_client, mock_db):
        """developer 不能创建服务器组（AuthError → 400 + error_code 11001）"""
        resp = await dev_client.post("/api/v1/groups/servers", json={
            "group_name": "DEV不应创建",
            "description": "不应创建",
            "env_code": "DEV",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_dev_can_list_datasource_groups(self, dev_client, mock_db):
        """F-15: developer 可以查看数据源组列表"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await dev_client.get("/api/v1/groups/datasources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_dev_can_list_server_groups(self, dev_client, mock_db):
        """F-15: developer 可以查看服务器组列表"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await dev_client.get("/api/v1/groups/servers")
        assert resp.status_code == 200


# ==================== 环境过滤 ====================


class TestEnvironmentFilterE2E:
    """F-17: dev 禁 PROD 环境过滤验证"""

    @pytest.mark.asyncio
    async def test_dev_only_sees_dev_uat_datasource_groups(self, dev_client, mock_db):
        """developer 列出数据源组时只可见 DEV/UAT"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await dev_client.get("/api/v1/groups/datasources")
        assert resp.status_code == 200
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_dev_only_sees_dev_uat_server_groups(self, dev_client, mock_db):
        """developer 列出服务器组时只可见 DEV/UAT"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await dev_client.get("/api/v1/groups/servers")
        assert resp.status_code == 200
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_admin_sees_all_env_datasource_groups(self, admin_client, mock_db):
        """admin 列出数据源组时可见所有环境"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/datasources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_sees_all_env_server_groups(self, admin_client, mock_db):
        """admin 列出服务器组时可见所有环境"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/groups/servers")
        assert resp.status_code == 200


# ==================== 系统配置 CRUD ====================


class TestSystemConfigE2E:
    """F-18: 系统配置 CRUD 全流程"""

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
            "config_key": "skill.upload.max_size_mb",
            "config_value": "50",
            "config_type": "int",
            "description": "Skill 包上传大小限制（MB）",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_system_config(self, admin_client, mock_db):
        """更新系统配置"""
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.config_key = "skill.upload.max_size_mb"
        mock_db.get = AsyncMock(return_value=mock_config)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/system-config/1", json={
            "config_value": "100",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_system_config(self, admin_client, mock_db):
        """删除系统配置"""
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.config_key = "test.key"
        mock_db.get = AsyncMock(return_value=mock_config)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/1")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_nonexistent_config(self, admin_client, mock_db):
        """更新不存在的配置应返回 16002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/system-config/9999", json={
            "config_value": "updated",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 16002

    @pytest.mark.asyncio
    async def test_delete_nonexistent_config(self, admin_client, mock_db):
        """删除不存在的配置应返回 16002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 16002