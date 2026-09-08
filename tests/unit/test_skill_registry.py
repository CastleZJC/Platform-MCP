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
    async def test_风险确认流记error带CONFIRM_REQUIRED(self):
        """BUG20260817 BUG-5 收紧：confirm 拦截该次调用 SQL 未执行，如实记 error；
        携带 token 重试成功后有独立 success 行，审计可对账"确认→执行"两跳。
        （取代 2026-08-16 的"confirm_token 豁免不计失败"决策）"""
        handler, mock_log = self._capture_handler(
            {
                "success": False,
                "error_code": "CONFIRM_REQUIRED",
                "message": "风险等级 HIGH，需二次确认：请将本响应中的 confirm_token 作为参数重新调用本工具完成执行",
                "confirm_token": "tok",
            }
        )
        await handler()
        assert mock_log.await_args.args[1] == "error"
        assert mock_log.await_args.kwargs.get("error_code") == "CONFIRM_REQUIRED"

    @pytest.mark.asyncio
    async def test_业务payload显式error_code_透传(self):
        """MULTI_STMT_HIGH_RISK / EMPTY_SQL / CONFIRM_TOKEN_INVALID 等显式码原样入审计"""
        handler, mock_log = self._capture_handler(
            {"success": False, "error_code": "MULTI_STMT_HIGH_RISK", "message": "高风险操作不可多语句执行"}
        )
        await handler()
        assert mock_log.await_args.args[1] == "error"
        assert mock_log.await_args.kwargs.get("error_code") == "MULTI_STMT_HIGH_RISK"

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


class TestDisabledSkillGate:
    """勘误5：pmcp_skill.status=DISABLED 的 Skill 在 MCP 层真实失效（路由/列举/调用三门）。"""

    def setup_method(self):
        self.registry = SkillRegistry()

    def test_set_disabled_and_is_disabled(self):
        self.registry.set_disabled_skills({"database"})
        assert self.registry.is_skill_disabled("database") is True
        assert self.registry.is_skill_disabled("server") is False

    def test_route_停用skill返回None(self):
        tool = ToolMeta(tool_name="execute_sql_text", display_name="执行SQL", description="d")
        skill = _make_skill("database", [tool])
        self.registry.register(skill)
        assert self.registry.route("execute_sql_text") is skill
        self.registry.set_disabled_skills({"database"})
        assert self.registry.route("execute_sql_text") is None

    def test_get_tool_meta_停用返回None(self):
        tool = ToolMeta(tool_name="t1", display_name="T1", description="d")
        self.registry.register(_make_skill("database", [tool]))
        assert self.registry.get_tool_meta("t1") is not None
        self.registry.set_disabled_skills({"database"})
        assert self.registry.get_tool_meta("t1") is None

    def test_list_all_tools_过滤停用skill(self):
        t1 = ToolMeta(tool_name="db_tool", display_name="DB", description="d")
        t2 = ToolMeta(tool_name="srv_tool", display_name="SRV", description="d")
        self.registry.register(_make_skill("database", [t1]))
        self.registry.register(_make_skill("server", [t2]))
        self.registry.set_disabled_skills({"database"})
        names = [t.tool_name for t in self.registry.list_all_tools()]
        assert names == ["srv_tool"]

    @pytest.mark.asyncio
    async def test_handler_停用skill拒绝调用并审计(self):
        t = ToolMeta(tool_name="db_tool", display_name="DB", description="d")
        skill = _make_skill("database", [t])
        skill.validate = AsyncMock(return_value={})
        skill.execute = AsyncMock(return_value={"ok": True})
        # 注册前 patch（闭包在注册时绑定 log_mcp_call）
        with patch(
            "platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock
        ) as mock_log:
            self.registry.register(skill)
            self.registry.set_disabled_skills({"database"})
            mcp = MagicMock()
            self.registry.register_all_tools(mcp)
            handler = mcp.add_tool.call_args[0][0]
            result = await handler(sql="SELECT 1")
        assert '"code": 10001' in result
        assert "已停用" in result
        # 状态门在执行前拦截：execute 不应被调用
        skill.execute.assert_not_called()
        # 审计如实记 error + SKILL_DISABLED
        assert mock_log.await_args.args[1] == "error"
        assert mock_log.await_args.kwargs.get("error_code") == "SKILL_DISABLED"

    @pytest.mark.asyncio
    async def test_handler_启用skill正常放行(self):
        t = ToolMeta(tool_name="db_tool", display_name="DB", description="d")
        skill = _make_skill("database", [t])
        skill.validate = AsyncMock(return_value={"sql": "SELECT 1"})
        skill.execute = AsyncMock(return_value={"success": True, "result": "ok"})
        with patch(
            "platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock
        ):
            self.registry.register(skill)
            self.registry.set_disabled_skills({"server"})  # 停用别的 skill
            mcp = MagicMock()
            self.registry.register_all_tools(mcp)
            handler = mcp.add_tool.call_args[0][0]
            result = await handler(sql="SELECT 1")
        assert '"code": 0' in result
        skill.execute.assert_awaited_once()


class TestBuiltinToolRoles:
    """架构 §19.5.7：database/server 执行类工具 roles 排除一般用户；ecosystem 工具全角色。"""

    def test_database_工具排除一般用户(self):
        from platform_mcp.skills.database import _build_tool_meta
        metas = _build_tool_meta()
        assert metas, "database 应有工具"
        for t in metas:
            assert t.roles == {"admin", "developer"}
            assert "user" not in t.roles

    def test_server_工具排除一般用户(self):
        from platform_mcp.skills.server import _build_tool_meta
        metas = _build_tool_meta()
        assert metas, "server 应有工具"
        for t in metas:
            assert t.roles == {"admin", "developer"}
            assert "user" not in t.roles

    def test_ecosystem_工具全角色可见(self):
        from platform_mcp.skills.ecosystem import _build_tool_meta
        metas = _build_tool_meta()
        assert metas, "ecosystem 应有工具"
        for t in metas:
            assert t.roles == {"admin", "developer", "user"}


class TestRoleFiltering:
    """V3.0 M3.5（架构 §19.5.7）：ToolMeta.roles + list_tools/路由按认证身份 role_code 动态过滤。"""

    def setup_method(self):
        self.registry = SkillRegistry()

    def test_默认roles为全角色(self):
        t = ToolMeta(tool_name="t1", display_name="T1", description="d")
        assert t.roles == {"admin", "developer", "user"}

    def test_list_all_tools_按角色过滤受限工具(self):
        open_tool = ToolMeta(tool_name="search_skills", display_name="S", description="d")
        priv_tool = ToolMeta(
            tool_name="execute_sql_text", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        self.registry.register(_make_skill("skill_ecosystem", [open_tool]))
        self.registry.register(_make_skill("database", [priv_tool]))
        # 一般用户：仅见全角色工具
        user_names = {t.tool_name for t in self.registry.list_all_tools("user")}
        assert user_names == {"search_skills"}
        # developer / admin：全见
        assert {t.tool_name for t in self.registry.list_all_tools("developer")} == {
            "search_skills", "execute_sql_text",
        }
        assert {t.tool_name for t in self.registry.list_all_tools("admin")} == {
            "search_skills", "execute_sql_text",
        }

    def test_list_all_tools_无角色不过滤(self):
        priv_tool = ToolMeta(
            tool_name="execute_sql_text", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        self.registry.register(_make_skill("database", [priv_tool]))
        # role_code=None（遗留 stdio 无 Key）→ 不过滤
        assert [t.tool_name for t in self.registry.list_all_tools()] == ["execute_sql_text"]
        assert [t.tool_name for t in self.registry.list_all_tools(None)] == ["execute_sql_text"]

    def test_route_角色不可见返回None(self):
        priv_tool = ToolMeta(
            tool_name="execute_sql_text", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        skill = _make_skill("database", [priv_tool])
        self.registry.register(skill)
        assert self.registry.route("execute_sql_text", "developer") is skill
        assert self.registry.route("execute_sql_text", "user") is None
        assert self.registry.route("execute_sql_text") is skill  # 无角色不过滤

    def test_get_tool_meta_角色不可见返回None(self):
        priv_tool = ToolMeta(
            tool_name="execute_sql_text", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        self.registry.register(_make_skill("database", [priv_tool]))
        assert self.registry.get_tool_meta("execute_sql_text", "admin") is not None
        assert self.registry.get_tool_meta("execute_sql_text", "user") is None

    def test_allowed_tool_names_按角色(self):
        open_tool = ToolMeta(tool_name="list_my_skills", display_name="L", description="d")
        priv_tool = ToolMeta(
            tool_name="execute_command", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        self.registry.register(_make_skill("skill_ecosystem", [open_tool]))
        self.registry.register(_make_skill("server", [priv_tool]))
        assert self.registry.allowed_tool_names("user") == {"list_my_skills"}
        assert self.registry.allowed_tool_names("admin") == {"list_my_skills", "execute_command"}

    def test_allowed_tool_names_叠加停用门(self):
        priv_tool = ToolMeta(tool_name="execute_command", display_name="E", description="d")
        self.registry.register(_make_skill("server", [priv_tool]))
        self.registry.set_disabled_skills({"server"})
        assert self.registry.allowed_tool_names("admin") == set()

    def test_全量注册角色矩阵_工具数32(self):
        """全量工具矩阵：总数 32；admin 32 / developer 31 / user 20
        （M4 增 submit_skill_artifact / get_skill_iteration_diff；2026-09-08 增 get_skill_file
        全角色可见——闭环「动态加载暴露」，CC 可取 SKILL.md 正文与附件）。"""
        from platform_mcp.mcp_server.skill.registry import get_skill_instance

        for code in ("database", "server", "skill_ecosystem", "skill_plaza", "skill_account"):
            inst = get_skill_instance(code)
            assert inst is not None
            self.registry.register(inst)
        assert len(self.registry.allowed_tool_names(None)) == 32
        assert len(self.registry.allowed_tool_names("admin")) == 32
        assert len(self.registry.allowed_tool_names("developer")) == 31
        assert len(self.registry.allowed_tool_names("user")) == 20
        # 生态新工具全角色可见（差异查询/产物回传/包内文件下发不限 developer）
        for tool in ("submit_skill_artifact", "get_skill_iteration_diff", "get_skill_file"):
            meta = self.registry.get_tool_meta(tool)
            assert meta is not None
            assert meta.roles == {"admin", "developer", "user"}

    @pytest.mark.asyncio
    async def test_handler_角色门拒绝并审计ROLE_FORBIDDEN(self):
        t = ToolMeta(
            tool_name="execute_sql_text", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        skill = _make_skill("database", [t])
        skill.validate = AsyncMock(return_value={})
        skill.execute = AsyncMock(return_value={"ok": True})
        with patch(
            "platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock
        ) as mock_log, patch(
            "platform_mcp.mcp_server.get_current_identity",
            return_value={"username": "user01", "role_code": "user"},
        ):
            self.registry.register(skill)
            mcp = MagicMock()
            self.registry.register_all_tools(mcp)
            handler = mcp.add_tool.call_args[0][0]
            result = await handler(sql="SELECT 1")
        assert '"code": 10004' in result
        skill.execute.assert_not_called()  # 角色门在执行前拦截
        assert mock_log.await_args.args[1] == "error"
        assert mock_log.await_args.kwargs.get("error_code") == "ROLE_FORBIDDEN"

    @pytest.mark.asyncio
    async def test_handler_角色允许正常放行(self):
        t = ToolMeta(
            tool_name="execute_sql_text", display_name="E", description="d",
            roles={"admin", "developer"},
        )
        skill = _make_skill("database", [t])
        skill.validate = AsyncMock(return_value={"sql": "SELECT 1"})
        skill.execute = AsyncMock(return_value={"success": True, "result": "ok"})
        with patch(
            "platform_mcp.mcp_server.call_log.log_mcp_call", new_callable=AsyncMock
        ), patch(
            "platform_mcp.mcp_server.get_current_identity",
            return_value={"username": "dev01", "role_code": "developer"},
        ):
            self.registry.register(skill)
            mcp = MagicMock()
            self.registry.register_all_tools(mcp)
            handler = mcp.add_tool.call_args[0][0]
            result = await handler(sql="SELECT 1")
        assert '"code": 0' in result
        skill.execute.assert_awaited_once()
