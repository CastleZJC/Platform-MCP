"""统一组资源可见性助手测试 — accessible_resource_ids

业务场景（技术架构说明文档 §19.5.4）：
- admin：返回 None（不限）
- developer：仅返回所属启用组内的资源 id 白名单；无组返回 []（空列表，非 None）
- 一般用户（user）：无 database/server 权限，返回 []
- 停用组（status=0）不参与可见性
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from platform_mcp.group.access import accessible_resource_ids


def _db_returning(*scalar_lists):
    """构造按调用次序返回 scalars().all() 结果的 AsyncMock db 会话"""
    db = MagicMock()
    results = []
    for vals in scalar_lists:
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(vals)
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    return db


class TestAccessibleResourceIds:
    @pytest.mark.asyncio
    async def test_admin_returns_none(self):
        db = _db_returning([])
        assert await accessible_resource_ids(db, user_id=1, role_code="admin", resource="datasource") is None
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_developer_with_groups_returns_whitelist(self):
        # 第一次查询：用户所属启用组 [10, 11]；第二次查询：组内数据源 [101, 102]
        db = _db_returning([10, 11], [101, 102])
        ids = await accessible_resource_ids(db, user_id=2, role_code="developer", resource="datasource")
        assert ids == [101, 102]

    @pytest.mark.asyncio
    async def test_developer_without_groups_returns_empty(self):
        db = _db_returning([], [])
        ids = await accessible_resource_ids(db, user_id=2, role_code="developer", resource="server")
        assert ids == []

    @pytest.mark.asyncio
    async def test_regular_user_returns_empty_without_query(self):
        # user 角色无 db/server 权限：直接空列表，不查组（防御性短路）
        db = _db_returning([])
        ids = await accessible_resource_ids(db, user_id=3, role_code="user", resource="datasource")
        assert ids == []
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_group_with_no_members_returns_empty(self):
        # 有组但组内无资源成员 → []
        db = _db_returning([10], [])
        ids = await accessible_resource_ids(db, user_id=2, role_code="developer", resource="datasource")
        assert ids == []

    @pytest.mark.asyncio
    async def test_dedup_and_sorted_ids(self):
        # 多组挂同一资源 → 去重；乱序 → 排序（便于断言与日志稳定）
        db = _db_returning([10, 11], [102, 101, 102])
        ids = await accessible_resource_ids(db, user_id=2, role_code="developer", resource="datasource")
        assert ids == [101, 102]

    @pytest.mark.asyncio
    async def test_invalid_resource_raises(self):
        db = _db_returning([])
        with pytest.raises(ValueError):
            await accessible_resource_ids(db, user_id=2, role_code="developer", resource="unknown")

    @pytest.mark.asyncio
    async def test_disabled_group_excluded(self):
        """停用组（status=0）不参与可见性：join 过滤后无组 → 空列表"""
        db = _db_returning([], [])
        ids = await accessible_resource_ids(db, user_id=2, role_code="developer", resource="datasource")
        assert ids == []
