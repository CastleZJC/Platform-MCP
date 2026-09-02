"""MCP 身份贯通测试 — McpContext.identity 与 list 工具按身份过滤（V3.0 M0，修复勘误 1）

业务场景：
- build_context 把 API Key 校验身份（user_id/username/role_code）完整放入 McpContext.identity
- database/server skill 的 list 工具把 identity 转为 user dict 传给 manager（组过滤生效）
- 无身份（遗留 stdio 无 Key 场景）→ identity=None → manager 不过滤（兼容）
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBuildContextIdentity:
    @pytest.mark.asyncio
    async def test_identity_from_contextvar(self):
        from platform_mcp.mcp_server import context as ctx_mod

        fake_identity = {"user_id": 2, "username": "dev01", "nickname": "开发者", "role_code": "developer"}
        # build_context 内部从 platform_mcp.mcp_server 局部导入 get_current_identity，需 patch 源模块
        with patch("platform_mcp.mcp_server.get_current_identity", return_value=fake_identity):
            ctx = ctx_mod.build_context("list_datasources", env_code="DEV")
        assert ctx.identity == fake_identity
        assert ctx.operator == "dev01"

    @pytest.mark.asyncio
    async def test_identity_none_when_unauthenticated(self):
        from platform_mcp.mcp_server import context as ctx_mod

        with patch("platform_mcp.mcp_server.get_current_identity", return_value=None):
            ctx = ctx_mod.build_context("list_datasources", env_code="DEV")
        assert ctx.identity is None


class TestListToolsPassIdentity:
    @pytest.mark.asyncio
    async def test_list_datasources_passes_user(self):
        from platform_mcp.skills.database import DatabaseSkill

        skill = DatabaseSkill()
        ctx = MagicMock()
        ctx.identity = {"user_id": 2, "username": "dev01", "role_code": "developer"}
        fake_manager = MagicMock()
        fake_manager.list_accessible_datasources = AsyncMock(return_value=[])
        with patch("platform_mcp.datasource.manager.datasource_manager", fake_manager):
            await skill._list_datasources({"env_code": "DEV"}, ctx)
        fake_manager.list_accessible_datasources.assert_awaited_once_with(
            "DEV", user={"id": 2, "role_code": "developer"}
        )

    @pytest.mark.asyncio
    async def test_list_datasources_no_identity_no_user(self):
        from platform_mcp.skills.database import DatabaseSkill

        skill = DatabaseSkill()
        ctx = MagicMock()
        ctx.identity = None
        fake_manager = MagicMock()
        fake_manager.list_accessible_datasources = AsyncMock(return_value=[])
        with patch("platform_mcp.datasource.manager.datasource_manager", fake_manager):
            await skill._list_datasources({"env_code": "DEV"}, ctx)
        fake_manager.list_accessible_datasources.assert_awaited_once_with("DEV", user=None)

    @pytest.mark.asyncio
    async def test_list_servers_passes_user(self):
        from platform_mcp.skills.server import ServerSkill

        skill = ServerSkill()
        ctx = MagicMock()
        ctx.identity = {"user_id": 2, "username": "dev01", "role_code": "developer"}
        fake_manager = MagicMock()
        fake_manager.list_accessible_servers = AsyncMock(return_value=[])
        with patch("platform_mcp.server.manager.server_manager", fake_manager):
            await skill._list_servers({"env_code": "DEV"}, ctx)
        fake_manager.list_accessible_servers.assert_awaited_once_with("DEV", user={"id": 2, "role_code": "developer"})
