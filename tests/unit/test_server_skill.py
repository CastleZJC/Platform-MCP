"""ServerSkill 单元测试 — 注册/路由/工具元数据"""

import pytest
from unittest.mock import AsyncMock, patch

from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.skills.server import ServerSkill, _TOOL_NAMES


class TestServerSkillRegistration:
    def test_skill_name(self):
        assert ServerSkill().skill_name() == "server"

    def test_supports_all_6_tools(self):
        sk = ServerSkill()
        for name in _TOOL_NAMES:
            assert sk.support(name), f"{name} not supported"

    def test_supports_unknown_returns_false(self):
        assert ServerSkill().support("unknown_tool") is False

    def test_list_tools_count(self):
        tools = ServerSkill().list_tools()
        assert len(tools) == 6

    def test_list_tools_returns_toolmeta(self):
        tools = ServerSkill().list_tools()
        assert all(isinstance(t, ToolMeta) for t in tools)

    def test_tool_names_match(self):
        tools = ServerSkill().list_tools()
        names = {t.tool_name for t in tools}
        assert names == _TOOL_NAMES

    def test_skill_decorator_marks_class(self):
        assert getattr(ServerSkill, "_skill_name", None) == "server"

    def test_audit_required_on_executing_tools(self):
        sk = ServerSkill()
        for t in sk.list_tools():
            if t.tool_name in ("execute_command", "upload_file", "download_file"):
                assert t.audit_required is True, f"{t.tool_name} should require audit"

    def test_audit_not_required_on_query_tools(self):
        sk = ServerSkill()
        for t in sk.list_tools():
            if t.tool_name in ("list_servers", "validate_command", "get_server_execution_status"):
                assert t.audit_required is False, f"{t.tool_name} should not require audit"


class TestServerSkillValidate:
    def setup_method(self):
        self.sk = ServerSkill()

    @pytest.mark.asyncio
    async def test_validate_execute_command_requires_server_code(self):
        from platform_mcp.common.exceptions import SkillError

        with pytest.raises(SkillError):
            await self.sk.validate("execute_command", {"command": "ls"})

    @pytest.mark.asyncio
    async def test_validate_execute_command_requires_command(self):
        from platform_mcp.common.exceptions import SkillError

        with pytest.raises(SkillError):
            await self.sk.validate("execute_command", {"server_code": "APP-SAMPLE-1"})

    @pytest.mark.asyncio
    async def test_validate_upload_requires_paths(self):
        from platform_mcp.common.exceptions import SkillError

        with pytest.raises(SkillError):
            await self.sk.validate("upload_file", {"server_code": "APP-SAMPLE-1", "local_path": "/x"})

    @pytest.mark.asyncio
    async def test_validate_download_requires_paths(self):
        from platform_mcp.common.exceptions import SkillError

        with pytest.raises(SkillError):
            await self.sk.validate("download_file", {"server_code": "APP-SAMPLE-1"})

    @pytest.mark.asyncio
    async def test_validate_command_passes_with_command(self):
        params = {"command": "ls"}
        result = await self.sk.validate("validate_command", params)
        assert result["command"] == "ls"

    @pytest.mark.asyncio
    async def test_validate_unknown_tool_returns_params(self):
        params = {"foo": "bar"}
        result = await self.sk.validate("unknown", params)
        assert result == params


class TestServerSkillExecute:
    def setup_method(self):
        self.sk = ServerSkill()

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            await self.sk.execute("unknown", {}, None)

    @pytest.mark.asyncio
    async def test_list_servers_returns_dict(self):
        with patch(
            "platform_mcp.server.manager.server_manager.list_accessible_servers",
            new_callable=AsyncMock,
            return_value=[{"server_code": "APP-SAMPLE-1"}],
        ):
            result = await self.sk.execute("list_servers", {}, None)
            assert result["total"] == 1
            assert result["servers"][0]["server_code"] == "APP-SAMPLE-1"

    @pytest.mark.asyncio
    async def test_validate_command_returns_risk_info(self):
        result = await self.sk.execute(
            "validate_command",
            {"command": "rm -rf /", "env_code": "DEV"},
            None,
        )
        assert result["risk_level"] == "CRITICAL"
        assert result["needs_confirm"] is True
