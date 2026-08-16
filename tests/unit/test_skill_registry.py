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


class TestHandlerBusinessFailureAudit:
    """BUG20260814163941 补充修复：success=False 的业务失败审计必须记 error。

    原实现只区分"抛没抛异常"——executor 内部捕获的业务失败（本地文件不存在、
    SFTP 错误、非零退出码）以 success=False 正常返回，被一律记成 success。
    """

    def setup_method(self):
        self.registry = SkillRegistry()

    def _capture_handler(self, execute_return):
        """注册前 patch —— registry 闭包在注册时绑定 log_mcp_call，注册后 patch 无效。"""
        t = ToolMeta(tool_name="upload_file", display_name="上传文件", description="d")
        skill = _make_skill("s", [t])
        skill.validate = AsyncMock(return_value={})
        skill.execute = AsyncMock(return_value=execute_return)
        with patch(
            "platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock
        ) as mock_log:
            self.registry.register(skill)
            mcp = MagicMock()
            self.registry.register_all_tools(mcp)
            handler = mcp.add_tool.call_args[0][0]
        return handler, mock_log

    @pytest.mark.asyncio
    async def test_业务失败记error并带error_message(self):
        handler, mock_log = self._capture_handler(
            {"success": False, "error_message": "本地文件不存在: D:/x.zip"}
        )
        await handler()
        mock_log.assert_awaited_once()
        assert mock_log.await_args.args[1] == "error"
        assert "本地文件不存在" in mock_log.await_args.kwargs["error"]
        assert mock_log.await_args.kwargs.get("error_code") == "10001"

    @pytest.mark.asyncio
    async def test_风险确认流不算失败(self):
        handler, mock_log = self._capture_handler(
            {"success": False, "message": "风险等级 HIGH，需要二次确认", "confirm_token": "tok"}
        )
        await handler()
        assert mock_log.await_args.args[1] == "success"

    @pytest.mark.asyncio
    async def test_message字段兜底(self):
        handler, mock_log = self._capture_handler(
            {"success": False, "message": "执行记录不存在或已过期"}
        )
        await handler()
        assert mock_log.await_args.args[1] == "error"
        assert "执行记录不存在" in mock_log.await_args.kwargs["error"]

    @pytest.mark.asyncio
    async def test_success_true正常记success(self):
        handler, mock_log = self._capture_handler({"success": True, "result": "ok"})
        await handler()
        assert mock_log.await_args.args[1] == "success"
