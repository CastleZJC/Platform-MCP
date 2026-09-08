"""manager 层组过滤测试 — V3.0 M0 组过滤下沉（修复勘误 1：MCP 层组过滤缺口）

业务场景（技术架构说明文档 §19.5.4）：
- user=None（脚本/遗留）与 admin：不加组过滤，返回全部启用数据源/服务器
- developer：仅所属启用组内对象；无组 → 空列表
- 一般用户（user 角色）：空列表（防御，registry 角色过滤在 M3 落地前的查询层兜底）
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _session_mock(execute_results):
    """构造 async 上下文 session 工厂：execute 按次序返回结果"""
    session = MagicMock()
    results = []
    for scalars_all in execute_results:
        r = MagicMock()
        r.scalars.return_value.all.return_value = list(scalars_all)
        r.all.return_value = list(scalars_all)  # 元组行查询（resource_group_names）直接 .all()
        results.append(r)
    session.execute = AsyncMock(side_effect=results)

    @asynccontextmanager
    async def _cm():
        yield session

    def factory():
        """get_session_factory() → session 工厂；再 () 得到 async ctx manager（两层调用，与生产代码一致）"""
        def _session_factory():
            return _cm()
        return _session_factory

    return session, factory


def _row(**kw):
    """构造 PmcpDatasource/PmcpServer 形态的行对象"""
    row = MagicMock()
    for k, v in kw.items():
        setattr(row, k, v)
    return row


_DS_DEFAULTS = dict(datasource_code="ds1", datasource_name="DS1", db_type="oracle", host="h",
                    port=1521, env_code="DEV", status=1)
_SVR_DEFAULTS = dict(server_code="sv1", server_name="SV1", host="h", ssh_port=22,
                     username="u", env_code="DEV", status=1)


class TestDatasourceManagerGroupFilter:
    @pytest.mark.asyncio
    async def test_no_user_no_filter(self):
        from platform_mcp.datasource import manager as m

        row = _row(**_DS_DEFAULTS)
        _, factory = _session_mock([[row], []])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.datasource_manager.list_accessible_datasources("DEV")
        assert len(result) == 1
        assert result[0]["datasource_code"] == "ds1"
        assert result[0]["groups"] == []  # 2026-09-08 响应附充分组字段（无组为空列表）

    @pytest.mark.asyncio
    async def test_admin_no_filter(self):
        from platform_mcp.datasource import manager as m

        row = _row(**_DS_DEFAULTS)
        _, factory = _session_mock([[row], []])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.datasource_manager.list_accessible_datasources(
                "DEV", user={"id": 1, "role_code": "admin"}
            )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_developer_whitelist(self):
        from platform_mcp.datasource import manager as m

        row = _row(**_DS_DEFAULTS)
        # 次序：access 组查询 [10] → 组内数据源 [5] → 主查询行（行对象 id=5 在白名单内）
        #       → 分组名查询 [(5, "CRM组")]（resource_group_names）
        row.id = 5
        _, factory = _session_mock([[10], [5], [row], [(5, "CRM组")]])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.datasource_manager.list_accessible_datasources(
                "DEV", user={"id": 2, "role_code": "developer"}
            )
        assert len(result) == 1
        assert result[0]["groups"] == ["CRM组"]

    @pytest.mark.asyncio
    async def test_developer_without_groups_empty(self):
        from platform_mcp.datasource import manager as m

        _, factory = _session_mock([[], []])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.datasource_manager.list_accessible_datasources(
                "DEV", user={"id": 2, "role_code": "developer"}
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_regular_user_empty(self):
        from platform_mcp.datasource import manager as m

        _, factory = _session_mock([])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.datasource_manager.list_accessible_datasources(
                "DEV", user={"id": 3, "role_code": "user"}
            )
        assert result == []


class TestServerManagerGroupFilter:
    @pytest.mark.asyncio
    async def test_developer_whitelist(self):
        from platform_mcp.server import manager as m

        row = _row(**_SVR_DEFAULTS)
        # 次序：access 组查询 → 组内服务器 → 主查询行 → 分组名查询
        row.id = 7
        _, factory = _session_mock([[10], [7], [row], [(7, "运维组")]])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.server_manager.list_accessible_servers(
                "DEV", user={"id": 2, "role_code": "developer"}
            )
        assert len(result) == 1
        assert result[0]["server_code"] == "sv1"
        assert result[0]["groups"] == ["运维组"]

    @pytest.mark.asyncio
    async def test_admin_no_filter(self):
        from platform_mcp.server import manager as m

        row = _row(**_SVR_DEFAULTS)
        _, factory = _session_mock([[row], []])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.server_manager.list_accessible_servers("DEV", user={"id": 1, "role_code": "admin"})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_regular_user_empty(self):
        from platform_mcp.server import manager as m

        _, factory = _session_mock([])
        with patch.object(m._db, "get_session_factory", factory):
            result = await m.server_manager.list_accessible_servers("DEV", user={"id": 3, "role_code": "user"})
        assert result == []
