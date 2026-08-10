"""5.1.5 Skill Registry 单元测试 — 注册/路由/查询/装饰器"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.mcp_server.skill.registry import SkillRegistry
from platform_mcp.mcp_server.skill.decorator import register_skill, get_pending_skills, clear_pending_skills


def _make_skill(name="test_skill", tools=None):
    skill = MagicMock()
    skill.skill_name.return_value = name
    skill.list_tools.return_value = tools or []
    return skill


class TestSkillRegistry:
    def setup_method(self):
        self.registry = SkillRegistry()

    def test_register_skill_stores_it(self):
        skill = _make_skill("db")
        self.registry.register(skill)
        assert self.registry.get_skill("db") is skill

    def test_get_skill_nonexistent_returns_none(self):
        assert self.registry.get_skill("nope") is None

    def test_route_finds_skill_by_tool_name(self):
        tool = ToolMeta(tool_name="execute_sql_text", display_name="执行SQL", description="desc")
        skill = _make_skill("db", [tool])
        self.registry.register(skill)
        assert self.registry.route("execute_sql_text") is skill

    def test_route_unknown_tool_returns_none(self):
        assert self.registry.route("unknown_tool") is None

    def test_list_all_tools_returns_metas(self):
        t1 = ToolMeta(tool_name="t1", display_name="T1", description="d1")
        t2 = ToolMeta(tool_name="t2", display_name="T2", description="d2")
        skill = _make_skill("s", [t1, t2])
        self.registry.register(skill)
        tools = self.registry.list_all_tools()
        assert len(tools) == 2
        names = [t.tool_name for t in tools]
        assert "t1" in names and "t2" in names

    def test_get_tool_meta(self):
        t = ToolMeta(tool_name="t1", display_name="T1", description="d1")
        self.registry.register(_make_skill("s", [t]))
        meta = self.registry.get_tool_meta("t1")
        assert meta is not None
        assert meta.tool_name == "t1"

    def test_multiple_skills_registered(self):
        t1 = ToolMeta(tool_name="a_tool", display_name="A", description="d")
        t2 = ToolMeta(tool_name="b_tool", display_name="B", description="d")
        self.registry.register(_make_skill("a", [t1]))
        self.registry.register(_make_skill("b", [t2]))
        assert self.registry.route("a_tool").skill_name() == "a"
        assert self.registry.route("b_tool").skill_name() == "b"

    def test_register_all_tools_calls_mcp(self):
        t = ToolMeta(tool_name="my_tool", display_name="MyTool", description="desc")
        skill = _make_skill("s", [t])
        self.registry.register(skill)
        mcp = MagicMock()
        self.registry.register_all_tools(mcp)
        mcp.add_tool.assert_called_once()


class TestRegisterSkillDecorator:
    def setup_method(self):
        clear_pending_skills()

    def test_decorator_marks_class(self):
        @register_skill("test")
        class MySkill:
            pass
        assert MySkill._skill_name == "test"

    def test_get_pending_returns_decorated(self):
        @register_skill("a")
        class SkillA:
            pass
        @register_skill("b")
        class SkillB:
            pass
        pending = get_pending_skills()
        assert len(pending) == 2

    def test_clear_pending_empties(self):
        @register_skill("x")
        class SkillX:
            pass
        clear_pending_skills()
        assert len(get_pending_skills()) == 0


class TestRegisterSingleTool:
    def setup_method(self):
        self.registry = SkillRegistry()

    def test_register_single_tool_调用mcp_add_tool(self):
        t = ToolMeta(tool_name="my_tool", display_name="MyTool", description="desc")
        skill = _make_skill("s", [t])
        skill.validate = AsyncMock(return_value={})
        skill.execute = AsyncMock(return_value={"ok": True})
        self.registry.register(skill)
        mcp = MagicMock()
        self.registry.register_all_tools(mcp)
        mcp.add_tool.assert_called_once()
        call_args = mcp.add_tool.call_args
        # add_tool(fn, name=, description=)
        assert call_args[1]["name"] == "my_tool"
        assert call_args[1]["description"] == "desc"

    def test_register_single_tool_生成handler函数(self):
        t = ToolMeta(tool_name="ht", display_name="HT", description="d")
        skill = _make_skill("s", [t])
        skill.validate = AsyncMock(return_value={})
        skill.execute = AsyncMock(return_value={"ok": True})
        self.registry.register(skill)
        mcp = MagicMock()
        self.registry.register_all_tools(mcp)
        assert mcp.add_tool.called
        # handler 是第一个位置参数
        assert callable(mcp.add_tool.call_args[0][0])

    @pytest.mark.asyncio
    async def test_handler_success_path(self):
        t = ToolMeta(tool_name="ht", display_name="HT", description="d")
        skill = _make_skill("s", [t])
        skill.validate = AsyncMock(return_value={"sql": "SELECT 1"})
        skill.execute = AsyncMock(return_value={"result": "ok"})
        self.registry.register(skill)

        mcp = MagicMock()
        self.registry.register_all_tools(mcp)
        captured_handler = mcp.add_tool.call_args[0][0]

        with patch("platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock):
            result = await captured_handler(sql="SELECT 1")
            assert '"code": 0' in result
            assert '"result": "ok"' in result

    @pytest.mark.asyncio
    async def test_handler_exception_path(self):
        t = ToolMeta(tool_name="ht", display_name="HT", description="d")
        skill = _make_skill("s", [t])
        skill.validate = AsyncMock(side_effect=Exception("validate fail"))
        self.registry.register(skill)

        mcp = MagicMock()
        self.registry.register_all_tools(mcp)
        captured_handler = mcp.add_tool.call_args[0][0]

        with patch("platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock):
            result = await captured_handler()
            assert '"code": 10001' in result
            assert "validate fail" in result
