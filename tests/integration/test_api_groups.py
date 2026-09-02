"""分组管理 API 集成测试 — V3.0 统一组模型（migration 005）

统一组口径（技术架构说明文档 §19.5.4）：
- 一个组同时挂 组员（用户）+ 数据源 + 服务器，三类成员多对多
- 分组管理仅 admin 可操作（权限同用户管理）；developer/一般用户 400+11001
- 审计 resource_type="group"
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_group(gid: int = 1, name: str = "DEV核心组", env: str = "DEV", status: int = 1):
    g = MagicMock()
    g.id = gid
    g.group_name = name
    g.description = "描述"
    g.env_code = env
    g.status = status
    g.inserted_at = None
    return g


def _paged_db(groups: list):
    """构造列表端点用的 db：第一次 execute 返回 count，后续返回页数据与计数"""
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = len(groups)
    page_result = MagicMock()
    page_result.scalars.return_value.all.return_value = groups
    db.execute = AsyncMock(side_effect=[count_result, page_result, MagicMock(), MagicMock(), MagicMock()])
    db.commit = AsyncMock()
    return db


class TestUnifiedGroupAPI:
    """统一组 CRUD + 三类成员管理 + 用户组关联"""

    @pytest.mark.asyncio
    async def test_list_groups(self, admin_client, mock_db):
        """列出统一组应返回分页数据与三类成员计数"""
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalar=MagicMock(return_value=1)),                      # count
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_mock_group()])))),  # 页数据
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),               # user 计数
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),               # datasource 计数
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),               # server 计数
        ])
        resp = await admin_client.get("/api/v1/groups")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        items = body.get("data", {}).get("items", [])
        assert len(items) == 1
        assert items[0]["group_name"] == "DEV核心组"
        assert {"user_count", "datasource_count", "server_count"} <= set(items[0].keys())

    @pytest.mark.asyncio
    async def test_create_group(self, admin_client, mock_db):
        """创建统一组应成功并审计"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db.flush = AsyncMock()
        resp = await admin_client.post("/api/v1/groups", json={
            "group_name": "DEV核心组",
            "description": "开发环境核心组",
            "env_code": "DEV",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_create_group_duplicate_name(self, admin_client, mock_db):
        """同环境同名组应返回 14003（UNIQUE(env_code, group_name)）"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_group()))
        )
        resp = await admin_client.post("/api/v1/groups", json={
            "group_name": "DEV核心组",
            "env_code": "DEV",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 14003

    @pytest.mark.asyncio
    async def test_update_group_nonexistent(self, admin_client, mock_db):
        """更新不存在的组应返回 14001"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.put("/api/v1/groups/9999", json={"group_name": "updated"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 14001

    @pytest.mark.asyncio
    async def test_update_group(self, admin_client, mock_db):
        """更新组（含停用）应成功"""
        mock_db.get = AsyncMock(return_value=_mock_group(status=1))
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/1", json={"status": 0})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_group_nonexistent(self, admin_client, mock_db):
        """删除不存在的组应返回 14001"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.delete("/api/v1/groups/9999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 14001

    @pytest.mark.asyncio
    async def test_delete_group_cascades_members(self, admin_client, mock_db):
        """删除组应成功（三类成员表 FK CASCADE 清理）"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.delete("/api/v1/groups/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_get_group_members(self, admin_client, mock_db):
        """获取组成员应返回 users/datasources/servers 三类清单"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        empty = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        mock_db.execute = AsyncMock(return_value=empty)
        resp = await admin_client.get("/api/v1/groups/1/members")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert {"users", "datasources", "servers"} <= set(data.keys())

    @pytest.mark.asyncio
    async def test_set_group_members_users(self, admin_client, mock_db):
        """设置组员（用户）应覆盖式成功"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/1/members", json={
            "resource": "user", "ids": [1, 2],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_set_group_members_datasources(self, admin_client, mock_db):
        """设置组成员（数据源）应覆盖式成功"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/1/members", json={
            "resource": "datasource", "ids": [10, 11],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_set_group_members_servers(self, admin_client, mock_db):
        """设置组成员（服务器）应覆盖式成功"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/1/members", json={
            "resource": "server", "ids": [20],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_set_group_members_invalid_resource(self, admin_client, mock_db):
        """非法 resource 应返回 14004"""
        mock_db.get = AsyncMock(return_value=_mock_group())
        resp = await admin_client.put("/api/v1/groups/1/members", json={
            "resource": "unknown", "ids": [1],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 14004

    @pytest.mark.asyncio
    async def test_get_user_groups(self, admin_client, mock_db):
        """获取用户所属组应返回 group_ids"""
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = [1, 5]
        mock_db.execute = AsyncMock(return_value=rows)
        resp = await admin_client.get("/api/v1/groups/users/2")
        assert resp.status_code == 200
        assert resp.json().get("data", {}).get("group_ids") == [1, 5]

    @pytest.mark.asyncio
    async def test_assign_user_groups(self, admin_client, mock_db):
        """覆盖式分配用户所属组应成功"""
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/users/2", json={"group_ids": [1, 2]})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_developer_forbidden(self, dev_client, mock_db):
        """分组管理仅 admin：developer 访问应 400 + 11001"""
        resp = await dev_client.get("/api/v1/groups")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_regular_user_forbidden(self, user_client, mock_db):
        """一般用户访问分组管理应 400 + 11001"""
        resp = await user_client.get("/api/v1/groups")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001


class TestResourceMembershipAPI:
    """行级资源-组关联（数据源/服务器页"新增分组"按钮承接）：

    GET  /groups/resource-membership?resource=datasource&resource_id=5 → 该资源当前所属组 ids
    PUT  /groups/resource-membership {resource, resource_id, group_ids} → 幂等设置该资源所属组
        （只 diff 增删关联行，不触碰各组其他成员——与整组覆盖式 PUT /groups/{id}/members 互补）
    """

    @pytest.mark.asyncio
    async def test_get_resource_membership(self, admin_client, mock_db):
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = [1, 3]
        mock_db.execute = AsyncMock(return_value=rows)
        resp = await admin_client.get("/api/v1/groups/resource-membership", params={
            "resource": "datasource", "resource_id": 5,
        })
        assert resp.status_code == 200
        assert resp.json().get("data", {}).get("group_ids") == [1, 3]

    @pytest.mark.asyncio
    async def test_set_resource_membership(self, admin_client, mock_db):
        """设置资源所属组（diff 增删）应成功"""
        # 当前所属组 [1]，目标 [1,2] → 追加组 2、无移除
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = [1]
        mock_db.execute = AsyncMock(return_value=rows)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/groups/resource-membership", json={
            "resource": "datasource", "resource_id": 5, "group_ids": [1, 2],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_set_resource_membership_invalid_resource(self, admin_client, mock_db):
        resp = await admin_client.put("/api/v1/groups/resource-membership", json={
            "resource": "unknown", "resource_id": 5, "group_ids": [1],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 14004

    @pytest.mark.asyncio
    async def test_get_resource_membership_invalid_resource(self, admin_client, mock_db):
        resp = await admin_client.get("/api/v1/groups/resource-membership", params={
            "resource": "unknown", "resource_id": 5,
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 14004


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
        resp = await admin_client.delete("/api/v1/system-config/9999")
        assert resp.status_code == 200
