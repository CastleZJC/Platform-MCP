"""M5 单元测试 — 通知分发服务（dispatch_notification / render_template）与审计路由纯函数

覆盖（F-37/F-39，架构 §19.5.5）：
- 模板渲染：参数替换 / 缺参空串 / 带空格占位符 / 非参数文本保留；
- 高危路由 _resolve_high_risk_notify_type：PROD+HIGH/CRITICAL 才命中，资源类型映射
  db_high_op / server_high_op，DEV/MEDIUM/无 risk_level 不命中；
- dispatch：未知类型静默、组不存在/停用组静默（F-37）、成员邮箱∪extra 去重、
  time 自动补、无收件人静默、DB 异常不外抛（通知故障不阻断业务）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.audit.logger import _resolve_high_risk_notify_type
from platform_mcp.notify.service import NOTIFY_TYPES, dispatch_notification, render_template


# ==================== render_template（F-39）====================

class TestRenderTemplate:
    def test_replaces_known_params(self):
        assert render_template("{{user}} 于 {{env}} 执行 {{risk}} 操作", {
            "user": "admin", "env": "PROD", "risk": "HIGH"}) == "admin 于 PROD 执行 HIGH 操作"

    def test_missing_param_renders_empty(self):
        """缺参/未定义键 → 空串（模板编辑容错，F-39）"""
        assert render_template("[{{known}}][{{unknown}}]", {"known": "v"}) == "[v][]"

    def test_placeholder_with_spaces(self):
        assert render_template("{{ user }}-{{risk}}", {"user": "u", "risk": "r"}) == "u-r"

    def test_plain_text_and_braces_kept(self):
        """非参数花括号文本原样保留（不误吞 JSON 片段等）"""
        assert render_template("a {b} c {{d}} e", {"d": "D"}) == "a {b} c D e"

    def test_param_value_non_string_coerced(self):
        assert render_template("N={{n}}", {"n": 0}) == "N=0"


# ==================== 高危路由纯函数（单一咽喉，覆盖 Web+MCP 双入口）====================

class TestResolveHighRiskNotifyType:
    def test_prod_high_sql_routes_db(self):
        assert _resolve_high_risk_notify_type("sql", "HIGH", "PROD") == "db_high_op"

    def test_prod_critical_datasource_routes_db(self):
        assert _resolve_high_risk_notify_type("datasource", "CRITICAL", "PROD") == "db_high_op"

    def test_prod_high_shell_routes_server(self):
        assert _resolve_high_risk_notify_type("shell", "HIGH", "PROD") == "server_high_op"

    def test_prod_critical_server_routes_server(self):
        assert _resolve_high_risk_notify_type("server", "CRITICAL", "PROD") == "server_high_op"

    def test_dev_high_not_routed(self):
        assert _resolve_high_risk_notify_type("sql", "HIGH", "DEV") is None

    def test_prod_medium_not_routed(self):
        assert _resolve_high_risk_notify_type("sql", "MEDIUM", "PROD") is None

    def test_no_risk_level_not_routed(self):
        assert _resolve_high_risk_notify_type("sql", None, "PROD") is None

    def test_non_exec_resource_not_routed(self):
        """非执行类资源（skill/permission 等）不进高危邮件组"""
        assert _resolve_high_risk_notify_type("skill", "HIGH", "PROD") is None

    def test_risk_level_case_insensitive(self):
        assert _resolve_high_risk_notify_type("sql", "high", "PROD") == "db_high_op"


# ==================== dispatch_notification ====================

def _group(enabled=1, notify_type="skill_review"):
    g = MagicMock()
    g.id = 7
    g.notify_type = notify_type
    g.enabled = enabled
    g.subject_template = "【{{env}}】{{user}} 提交 {{resource}}"
    g.body_template = "操作人 {{user}}\n资源 {{resource}}\n时间 {{time}}"
    return g


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _rows_result(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _session_with(execute_results):
    """构造 get_session_factory()() 两层调用 mock：factory() → maker，maker() → async ctx → session。"""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    maker = MagicMock(return_value=_Ctx())
    factory = MagicMock(return_value=maker)
    return factory, session


PARAMS = {"user": "dev01", "resource": "SKILL-X", "env": "PROD"}


class TestDispatchNotification:
    @pytest.mark.asyncio
    async def test_unknown_type_returns_zero_without_db(self):
        with patch("platform_mcp.common.database.get_session_factory") as factory:
            assert await dispatch_notification("not_a_type", {}, source="test") == 0
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_absent_silent(self):
        """未 seed 组静默返回 0（F-37）"""
        factory, session = _session_with([_scalar_result(None)])
        with patch("platform_mcp.common.database.get_session_factory", factory):
            assert await dispatch_notification("skill_review", PARAMS, source="test") == 0
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_group_silent(self):
        """停用组静默返回 0（F-37 验收项）"""
        factory, session = _session_with([_scalar_result(_group(enabled=0))])
        with patch("platform_mcp.common.database.get_session_factory", factory):
            assert await dispatch_notification("skill_review", PARAMS, source="test") == 0
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_recipients_silent(self):
        """无成员且无直发目标 → 0（不落空收件件）"""
        factory, session = _session_with([
            _scalar_result(_group()),
            _rows_result([(1, None), (2, "")]),  # 成员均无邮箱
        ])
        with patch("platform_mcp.common.database.get_session_factory", factory):
            assert await dispatch_notification("skill_review", PARAMS, source="test") == 0
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_members_union_extra_dedup_by_email(self):
        """收件人 = 组成员邮箱 ∪ extra（按邮箱去重，extra 覆盖 user_id，F-37）"""
        factory, session = _session_with([
            _scalar_result(_group()),
            _rows_result([(1, "a@x.com"), (2, None), (3, "b@x.com")]),
        ])
        extra = [(9, "a@x.com"), (None, "c@x.com")]  # a 重复（覆盖 user_id=9）、c 直发
        with patch("platform_mcp.common.database.get_session_factory", factory):
            count = await dispatch_notification(
                "skill_review", PARAMS, source="review", extra_recipients=extra
            )
        assert count == 3  # a@x.com / b@x.com / c@x.com
        assert session.add.call_count == 3
        mails = [c.args[0] for c in session.add.call_args_list]
        by_rcpt = {m.recipient: m for m in mails}
        assert set(by_rcpt) == {"a@x.com", "b@x.com", "c@x.com"}
        assert by_rcpt["a@x.com"].recipient_user_id == 9  # extra 覆盖
        assert by_rcpt["b@x.com"].recipient_user_id == 3
        assert by_rcpt["c@x.com"].recipient_user_id is None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_template_rendered_and_time_autofilled(self):
        """模板渲染注入实际值；缺 time 自动补当前时间（F-39）"""
        factory, session = _session_with([
            _scalar_result(_group()),
            _rows_result([(1, "a@x.com")]),
        ])
        with patch("platform_mcp.common.database.get_session_factory", factory):
            await dispatch_notification("skill_review", PARAMS, source="review", trace_id="T1")
        mail = session.add.call_args.args[0]
        assert mail.subject == "【PROD】dev01 提交 SKILL-X"
        assert "操作人 dev01" in mail.body
        assert "时间 " in mail.body  # time 自动补非空
        assert mail.source == "review"
        assert mail.trace_id == "T1"

    @pytest.mark.asyncio
    async def test_db_failure_swallowed(self):
        """通知链路 DB 故障返回 0 不外抛（不阻断业务，部署原则 #5）"""
        factory, _ = _session_with(RuntimeError("db down"))
        with patch("platform_mcp.common.database.get_session_factory", factory):
            assert await dispatch_notification("skill_review", PARAMS, source="test") == 0


def test_notify_types_registry():
    """四提醒事项与架构 §19.5.5 定稿一致"""
    assert NOTIFY_TYPES == ("db_high_op", "server_high_op", "skill_review", "user_mgmt")
