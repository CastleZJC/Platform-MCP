"""E2E 测试 — V3.0 统一组管理全流程（migration 005）

测试策略（技术架构说明文档 §19.5.4）：
1. 统一组 CRUD + 三类成员（组员/数据源/服务器）管理
2. 用户-组关联（覆盖式）
3. 角色权限：分组管理仅 admin（developer/一般用户 400+11001）
4. Web 列表组过滤：developer 仅所属组（经 access 助手）；admin 直通
5. 系统配置 CRUD（沿用 V2.1）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_group(gid: int = 1, name: str = "DEV核心组"):
    g = MagicMock()
    g.id = gid
    g.group_name = name
    g.description = "描述"
    g.status = 1
    g.inserted_at = None
    return g


def _empty_scalars():
    r = MagicMock()
    r.scalar.return_value = 0
    r.scalars.return_value.all.return_value = []
    return r


# ==================== 统一组 CRUD + 成员 ====================


class TestUnifiedGroupE2E:
    """统一组全流程（创建→三类成员分配→更新→删除）"""

    @pytest.mark.asyncio
    async def test_create_group(self, admin_client, mock_db):
        """创建统一组"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/groups", json={
            "group_name": "DEV核心组",
            "description": "开发环境核心组",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_list_groups(self, admin_client, mock_db):
        """列出统一组"""
        mock_db.execute = AsyncMock(return_value=_empty_scalars())
        resp = await admin_client.get("/api/v1/groups")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "items" in resp.json().get("data", {})

    @pytest.mark.asyncio
    async def test_update_group(self, admin_client, mock_db):
        """更新组（名称/描述/停用）"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/1", json={
            "group_name": "DEV核心组V2",
            "status": 0,
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_group_not_allowed(self, admin_client, mock_db):
        """组不提供删除（仅停用）：DELETE 端点已移除，应 405"""
        resp = await admin_client.delete("/api/v1/groups/1")
        assert resp.status_code == 405

    @pytest.mark.asyncio
    async def test_set_group_members_three_types(self, admin_client, mock_db):
        """三类成员均可分配（组员仅 developer 角色，数据源/服务器不校验角色）"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        role_result = MagicMock()
        role_result.all.return_value = [(1, "dev1", "developer"), (2, "dev2", "developer")]
        # 次序对应循环：user（角色核查→delete）→ datasource（delete）→ server（delete）
        mock_db.execute = AsyncMock(side_effect=[role_result, MagicMock(), MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()
        for resource, ids in (("user", [1, 2]), ("datasource", [10, 11]), ("server", [20])):
            resp = await admin_client.put("/api/v1/groups/1/members", json={
                "resource": resource, "ids": ids,
            })
            assert resp.status_code == 200, f"{resource} 分配失败"
            assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_get_group_members(self, admin_client, mock_db):
        """获取组三类成员清单"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        mock_db.execute = AsyncMock(return_value=_empty_scalars())
        resp = await admin_client.get("/api/v1/groups/1/members")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert {"users", "datasources", "servers"} <= set(data.keys())


# ==================== 用户-组关联 ====================


class TestUserGroupE2E:
    """用户-组关联全流程（覆盖式）"""

    @pytest.mark.asyncio
    async def test_assign_user_groups(self, admin_client, mock_db):
        """分配用户到多个组（developer 角色）"""
        role_result = MagicMock()
        role_result.scalar_one_or_none.return_value = "developer"
        mock_db.execute = AsyncMock(side_effect=[role_result, MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/users/2", json={"group_ids": [1, 2]})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_get_user_groups(self, admin_client, mock_db):
        """获取用户所属组"""
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = [1, 2]
        mock_db.execute = AsyncMock(return_value=rows)
        resp = await admin_client.get("/api/v1/groups/users/1")
        assert resp.status_code == 200
        assert resp.json().get("data", {}).get("group_ids") == [1, 2]

    @pytest.mark.asyncio
    async def test_assign_user_overwrites_previous(self, admin_client, mock_db):
        """覆盖式分配：再次分配替换旧关联（两次均过 developer 角色核查）"""
        role_result = MagicMock()
        role_result.scalar_one_or_none.return_value = "developer"
        mock_db.execute = AsyncMock(side_effect=[role_result, MagicMock(), role_result, MagicMock()])
        mock_db.commit = AsyncMock()
        resp1 = await admin_client.put("/api/v1/groups/users/2", json={"group_ids": [1]})
        assert resp1.status_code == 200
        assert resp1.json()["code"] == 0
        resp2 = await admin_client.put("/api/v1/groups/users/2", json={"group_ids": [2, 3]})
        assert resp2.status_code == 200
        assert resp2.json()["code"] == 0


# ==================== 角色权限（三角色） ====================


class TestRolePermissionE2E:
    """分组管理仅 admin；developer/一般用户 400 + 11001"""

    @pytest.mark.asyncio
    async def test_dev_cannot_create_group(self, dev_client, mock_db):
        resp = await dev_client.post("/api/v1/groups", json={
            "group_name": "DEV不应创建",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_dev_cannot_list_groups(self, dev_client, mock_db):
        resp = await dev_client.get("/api/v1/groups")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_regular_user_cannot_list_groups(self, user_client, mock_db):
        """一般用户（V3.0 第三角色）无分组管理权限"""
        resp = await user_client.get("/api/v1/groups")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_regular_user_cannot_list_datasources(self, user_client, mock_db):
        """一般用户无 database 权限：数据源列表 400 + 11001"""
        resp = await user_client.get("/api/v1/datasources")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_regular_user_cannot_list_servers(self, user_client, mock_db):
        """一般用户无 server 权限：服务器列表 400 + 11001"""
        resp = await user_client.get("/api/v1/servers")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_admin_can_list_groups(self, admin_client, mock_db):
        mock_db.execute = AsyncMock(return_value=_empty_scalars())
        resp = await admin_client.get("/api/v1/groups")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_regular_user_cannot_test_datasource(self, user_client, mock_db):
        """一般用户无 database 权限：测试连接端点同样 400 + 11001"""
        resp = await user_client.post("/api/v1/datasources/1/test")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_regular_user_cannot_test_server(self, user_client, mock_db):
        """一般用户无 server 权限：服务器测试连接端点 400 + 11001"""
        resp = await user_client.post("/api/v1/servers/1/test")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001


# ==================== Web 列表组过滤（access 助手贯通） ====================


class TestWebListGroupFilterE2E:
    """F-22：Web 层列表经 access 助手过滤（admin 直通 / dev 无组为空）"""

    @pytest.mark.asyncio
    async def test_dev_without_groups_sees_no_datasources(self, dev_client, mock_db):
        """无组 dev → 数据源列表为空（R-06 裁决）"""
        # execute 次序：access 组查询 [] → 主 count → 主 page（行空 → 无组名 join）
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalar=MagicMock(return_value=0)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        resp = await dev_client.get("/api/v1/datasources")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert data.get("total") == 0
        assert data.get("items") == []

    @pytest.mark.asyncio
    async def test_admin_sees_all_datasources_unfiltered(self, admin_client, mock_db):
        """admin 直通：不触发 access 查询（仅 count + page）"""
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalar=MagicMock(return_value=0)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        resp = await admin_client.get("/api/v1/datasources")
        assert resp.status_code == 200
        assert resp.json().get("data", {}).get("total") == 0

    @pytest.mark.asyncio
    async def test_dev_without_groups_sees_no_servers(self, dev_client, mock_db):
        """无组 dev → 服务器列表为空"""
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalar=MagicMock(return_value=0)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        resp = await dev_client.get("/api/v1/servers")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert data.get("total") == 0


# ==================== 系统配置 CRUD（沿用 V2.1） ====================


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
    async def test_put_system_config_upsert(self, admin_client, mock_db):
        """按键 upsert 创建系统配置（未落库键创建行）"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/system-config/skill.max_upload_size_mb", json={
            "config_value": "50",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_update_system_config(self, admin_client, mock_db):
        """更新系统配置（按键，已有行覆盖）"""
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.config_key = "skill.max_upload_size_mb"
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_config
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/system-config/skill.max_upload_size_mb", json={
            "config_value": "100",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_system_config(self, admin_client, mock_db):
        """删除系统配置（按键重置回默认）"""
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.config_key = "test.key"
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_config
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/test.key")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_post_system_config_removed(self, admin_client, mock_db):
        """独立创建端点已移除（按键 upsert 承接）"""
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "skill.max_upload_size_mb",
            "config_value": "50",
        })
        assert resp.status_code == 405

    @pytest.mark.asyncio
    async def test_delete_nonexistent_config(self, admin_client, mock_db):
        """删除不存在的配置应返回 16002"""
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/absent.key")
        assert resp.status_code == 200
        assert resp.json()["code"] == 16002
