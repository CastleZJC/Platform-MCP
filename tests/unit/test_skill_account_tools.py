"""单元测试 — Skill 账户/审核 MCP 工具（V3.0 M3.5，架构 §19.5.4 / §19.5.7，双端承接）

覆盖：工具元数据（4 工具、review_skill 仅 admin、其余三角色全可见、描述中英并列、签名可构建）/
参数校验 / review_skill（委托 SkillReviewService，approve/merge/reject 三动作 + admin 门错误透传）/
query_audit_logs（admin 全量透传 operator、非 admin 强制收敛为本人 username、分页/过滤透传）/
update_profile（改 nickname/email/locale + 审计 resource_type=permission channel=mcp + 用户不存在）/
change_password（校验当前密码、成功改密、失败 11004 留痕、明文口令不落审计、用户不存在）/ 身份贯通。

委托的审核/审计/认证服务函数直接 patch（隔离 DB 与口令哈希），会话经 patch get_session_factory
产出伪 session（get/flush/commit/rollback 可控）。
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.auth.models import PmcpUser
from platform_mcp.common.exceptions import SkillError
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    ReviewResult,
    SkillReviewError,
)
from platform_mcp.skills.ecosystem.account_tools import SkillAccountToolsSkill

ADMIN = {"user_id": 1, "username": "admin", "role_code": "admin", "locale": "zh-CN"}
ADMIN_EN = {"user_id": 1, "username": "admin", "role_code": "admin", "locale": "en-US"}
OWNER = {"user_id": 2, "username": "dev01", "role_code": "developer", "locale": "zh-CN"}
USER = {"user_id": 3, "username": "user01", "role_code": "user", "locale": "zh-CN"}

_AT = "platform_mcp.skills.ecosystem.account_tools"


def make_context(identity=None, trace_id="t-account"):
    ctx = MagicMock()
    ctx.identity = identity
    ctx.trace_id = trace_id
    return ctx


def make_review_result(**kw) -> ReviewResult:
    defaults = dict(
        skill_id=1, skill_code="demo", action="review_approve",
        old_status="PENDING_REVIEW", new_status="ENABLED",
        share_status="shared", plaza_id=10, review_comment=None,
    )
    defaults.update(kw)
    return ReviewResult(**defaults)


def make_user(**kw) -> PmcpUser:
    defaults = dict(
        id=2, username="dev01", password="oldhashed", nickname="Dev One",
        email="dev@example.com", locale="zh-CN", status=1,
    )
    defaults.update(kw)
    return PmcpUser(**defaults)


@pytest.fixture
def skill() -> SkillAccountToolsSkill:
    return SkillAccountToolsSkill()


@pytest.fixture
def mock_session():
    """patch get_session_factory：_session_scope 产出可控伪 session（delegated 函数另行 patch）。"""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.get = AsyncMock(return_value=None)
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    exec_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)
    session._exec_result = exec_result

    @contextlib.asynccontextmanager
    async def _cm():
        yield session

    def _factory():
        return _cm()

    with patch("platform_mcp.skills.ecosystem.get_session_factory", return_value=_factory):
        yield session


# ==================== 元数据 / 校验 ====================


class TestAccountToolsMeta:
    def test_skill_name与support(self, skill):
        assert skill.skill_name() == "skill_account"
        assert skill.support("review_skill") is True
        assert skill.support("change_password") is True
        assert skill.support("execute_sql_text") is False

    def test_四工具齐备(self, skill):
        names = {m.tool_name for m in skill.list_tools()}
        assert names == {"review_skill", "query_audit_logs", "update_profile", "change_password"}

    def test_review仅admin其余全角色(self, skill):
        metas = {m.tool_name: m for m in skill.list_tools()}
        # §19.5.7：review_skill 仅 admin（对应 Web 审核弹窗双端承接）
        assert metas["review_skill"].roles == {"admin"}
        for name in ("query_audit_logs", "update_profile", "change_password"):
            assert metas[name].roles == {"admin", "developer", "user"}

    def test_描述中英并列(self, skill):
        for meta in skill.list_tools():
            assert "/" in meta.description  # 中英并列分隔

    def test_签名可构建(self, skill):
        from platform_mcp.mcp_server.skill.registry import _build_handler_signature
        for meta in skill.list_tools():
            _build_handler_signature(meta.input_schema)  # 不抛即通过

    async def test_review缺skill_id被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("review_skill", {"action": "approve"})

    async def test_review非法action被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("review_skill", {"skill_id": 1, "action": "publish"})

    async def test_review合法action通过(self, skill):
        params = {"skill_id": 1, "action": "merge"}
        assert await skill.validate("review_skill", params) == params

    async def test_未知工具execute抛NotImplemented(self, skill):
        with pytest.raises(NotImplementedError):
            await skill.execute("nope", {}, make_context(ADMIN))


# ==================== review_skill（仅 admin，委托审核服务）====================


class TestReviewSkill:
    async def test_approve委托审核服务(self, skill, mock_session):
        result = make_review_result(action="review_approve", new_status="ENABLED")
        with patch(f"{_AT}.SkillReviewService") as SvcCls:
            svc = SvcCls.return_value
            svc.review = AsyncMock(return_value=result)
            res = await skill.execute(
                "review_skill", {"skill_id": 1, "action": "approve", "comment": "ok"}, make_context(ADMIN)
            )
        assert res["success"] is True
        assert res["new_status"] == "ENABLED"
        assert res["skill_id"] == 1
        svc.review.assert_awaited_once()
        args, kwargs = svc.review.await_args
        assert args[0].is_admin is True  # actor 由身份贯通
        assert args[1] == 1  # skill_id
        assert args[2] == "approve"  # action
        assert kwargs["comment"] == "ok"

    async def test_merge委托并透传comment(self, skill, mock_session):
        result = make_review_result(action="review_merge", new_status="SHARE_ITERATION", review_comment="并入 v2")
        with patch(f"{_AT}.SkillReviewService") as SvcCls:
            svc = SvcCls.return_value
            svc.review = AsyncMock(return_value=result)
            res = await skill.execute(
                "review_skill", {"skill_id": 7, "action": "merge", "comment": "并入 v2"}, make_context(ADMIN_EN)
            )
        assert res["new_status"] == "SHARE_ITERATION"
        assert res["review_comment"] == "并入 v2"
        # 英文 locale → 消息取英文
        assert "Review completed" in res["message"]
        assert svc.review.await_args.args[2] == "merge"

    async def test_reject委托(self, skill, mock_session):
        result = make_review_result(action="review_reject", new_status="REJECTED", review_comment="描述不清")
        with patch(f"{_AT}.SkillReviewService") as SvcCls:
            svc = SvcCls.return_value
            svc.review = AsyncMock(return_value=result)
            res = await skill.execute(
                "review_skill", {"skill_id": 3, "action": "reject", "comment": "描述不清"}, make_context(ADMIN)
            )
        assert res["new_status"] == "REJECTED"
        assert res["review_comment"] == "描述不清"

    async def test_审核服务拒绝错误透传(self, skill, mock_session):
        # 非 PENDING_REVIEW / 非 admin 等由 SkillReviewService 裁决，传输层如实透传错误码
        with patch(f"{_AT}.SkillReviewService") as SvcCls:
            svc = SvcCls.return_value
            svc.review = AsyncMock(side_effect=SkillReviewError("仅 admin 可审核", code=CODE_FORBIDDEN))
            with pytest.raises(SkillReviewError) as ei:
                await skill.execute("review_skill", {"skill_id": 1, "action": "approve"}, make_context(OWNER))
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_缺身份拒绝(self, skill, mock_session):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("review_skill", {"skill_id": 1, "action": "approve"}, make_context(None))
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== query_audit_logs（admin 全量 / 其他仅本人）====================


class TestQueryAuditLogs:
    async def test_admin全量并透传过滤(self, skill, mock_session):
        items = [{"id": 1, "operator": "admin"}, {"id": 2, "operator": "dev01"}]
        with patch(f"{_AT}.query_logs", new=AsyncMock(return_value=(items, 2))) as ql:
            res = await skill.execute(
                "query_audit_logs",
                {"page": 2, "page_size": 10, "operator": "dev01", "resource_type": "skill", "risk_level": "HIGH"},
                make_context(ADMIN),
            )
        assert res["scope"] == "all"
        assert res["total"] == 2
        assert res["page"] == 2
        assert res["page_size"] == 10
        assert res["items"] == items
        # admin 可自由指定 operator 过滤（全量可见性）
        assert ql.await_args.kwargs["operator"] == "dev01"
        assert ql.await_args.kwargs["resource_type"] == "skill"
        assert ql.await_args.kwargs["risk_level"] == "HIGH"

    async def test_非admin强制收敛operator为本人(self, skill, mock_session):
        with patch(f"{_AT}.query_logs", new=AsyncMock(return_value=([], 0))) as ql:
            res = await skill.execute(
                "query_audit_logs", {"operator": "someone-else"}, make_context(OWNER)
            )
        assert res["scope"] == "self"
        # 忽略传入 operator，强制收敛为本人 username（同 Web 审计页可见性）
        assert ql.await_args.kwargs["operator"] == "dev01"

    async def test_一般用户仅见自己(self, skill, mock_session):
        with patch(f"{_AT}.query_logs", new=AsyncMock(return_value=([], 0))) as ql:
            res = await skill.execute("query_audit_logs", {}, make_context(USER))
        assert res["scope"] == "self"
        assert ql.await_args.kwargs["operator"] == "user01"
        assert ql.await_args.kwargs["page"] == 1  # 默认分页
        assert ql.await_args.kwargs["page_size"] == 20

    async def test_缺身份拒绝(self, skill, mock_session):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("query_audit_logs", {}, make_context(None))
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== update_profile（个人设置）====================


class TestUpdateProfile:
    async def test_更新昵称邮箱语言并审计(self, skill, mock_session):
        user = make_user()
        mock_session.get = AsyncMock(return_value=user)
        with patch(f"{_AT}.write_audit_log", new=AsyncMock()) as audit:
            res = await skill.execute(
                "update_profile",
                {"nickname": "NewNick", "email": "new@ex.com", "locale": "en-US"},
                make_context(OWNER),
            )
        assert res["success"] is True
        assert user.nickname == "NewNick"
        assert user.email == "new@ex.com"
        assert user.locale == "en-US"
        assert len(res["changes"]) == 3
        kwargs = audit.await_args.kwargs
        assert kwargs["resource_type"] == "permission"
        assert kwargs["result_status"] == "success"
        assert kwargs["extra_data"]["channel"] == "mcp"  # MCP 通道归属
        assert kwargs["operator"] == "dev01"

    async def test_仅改昵称_部分字段(self, skill, mock_session):
        user = make_user(email="keep@ex.com", locale="zh-CN")
        mock_session.get = AsyncMock(return_value=user)
        with patch(f"{_AT}.write_audit_log", new=AsyncMock()):
            res = await skill.execute("update_profile", {"nickname": "OnlyNick"}, make_context(OWNER))
        assert res["changes"] == ["nickname=OnlyNick"]
        assert user.email == "keep@ex.com"  # 未传字段不动
        assert user.locale == "zh-CN"

    async def test_用户不存在(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("update_profile", {"nickname": "x"}, make_context(OWNER))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_locale非法被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("update_profile", {"locale": "fr-FR"})

    async def test_无字段被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("update_profile", {})

    async def test_缺身份拒绝(self, skill, mock_session):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("update_profile", {"nickname": "x"}, make_context(None))
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== change_password（校验当前密码，明文不落审计）====================


class TestChangePassword:
    async def test_改密成功(self, skill, mock_session):
        user = make_user(password="oldhashed")
        mock_session.get = AsyncMock(return_value=user)
        with patch(f"{_AT}.verify_password", return_value=True) as vp, \
                patch(f"{_AT}.hash_password", return_value="newhashed") as hp, \
                patch(f"{_AT}.write_audit_log", new=AsyncMock()) as audit:
            res = await skill.execute(
                "change_password", {"old_password": "Old#1", "new_password": "New#2"}, make_context(OWNER)
            )
        assert res["success"] is True
        vp.assert_called_once_with("Old#1", "oldhashed")
        hp.assert_called_once_with("New#2")
        assert user.password == "newhashed"
        kwargs = audit.await_args.kwargs
        assert kwargs["result_status"] == "success"
        assert kwargs["resource_type"] == "permission"
        assert kwargs["extra_data"]["channel"] == "mcp"

    async def test_当前密码错误返回11004并留痕(self, skill, mock_session):
        user = make_user(password="oldhashed")
        mock_session.get = AsyncMock(return_value=user)
        with patch(f"{_AT}.verify_password", return_value=False), \
                patch(f"{_AT}.hash_password") as hp, \
                patch(f"{_AT}.write_audit_log", new=AsyncMock()) as audit:
            with pytest.raises(SkillReviewError) as ei:
                await skill.execute(
                    "change_password", {"old_password": "Wrong", "new_password": "New#2"}, make_context(OWNER)
                )
        assert ei.value.error_code == 11004
        hp.assert_not_called()  # 未通过校验不改密
        assert user.password == "oldhashed"
        kwargs = audit.await_args.kwargs
        assert kwargs["result_status"] == "error"
        assert kwargs["error_code"] == "11004"

    async def test_明文口令不落审计(self, skill, mock_session):
        user = make_user(password="oldhashed")
        mock_session.get = AsyncMock(return_value=user)
        with patch(f"{_AT}.verify_password", return_value=True), \
                patch(f"{_AT}.hash_password", return_value="newhashed"), \
                patch(f"{_AT}.write_audit_log", new=AsyncMock()) as audit:
            await skill.execute(
                "change_password",
                {"old_password": "PlainOld#1", "new_password": "PlainNew#2"},
                make_context(OWNER),
            )
        # 任一次审计调用的任意字段都不得出现明文口令（request_summary 仅记动作）
        for call in audit.await_args_list:
            blob = str(call.kwargs)
            assert "PlainOld#1" not in blob
            assert "PlainNew#2" not in blob

    async def test_用户不存在(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute(
                "change_password", {"old_password": "a", "new_password": "b"}, make_context(OWNER)
            )
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_缺old_password被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("change_password", {"new_password": "b"})

    async def test_缺new_password被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("change_password", {"old_password": "a"})

    async def test_缺身份拒绝(self, skill, mock_session):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute(
                "change_password", {"old_password": "a", "new_password": "b"}, make_context(None)
            )
        assert ei.value.error_code == CODE_FORBIDDEN
