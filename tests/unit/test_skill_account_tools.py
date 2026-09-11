"""单元测试 — Skill 账户/审核 MCP 工具（V3.0 M3.5，架构 §19.5.4 / §19.5.7，双端承接）

覆盖：工具元数据（2 工具、review_skill 仅 admin、query_audit_logs 三角色全可见、描述中英并列、
签名可构建）/ 参数校验 / review_skill（委托 SkillReviewService，approve/merge/reject 三动作 +
admin 门错误透传、响应含 generated_by/artifact_hint 补足提示——批次 5.1）/ query_audit_logs
（admin 全量透传 operator、非 admin 强制收敛为本人 username、分页/过滤透传）/ 身份贯通。

个人设置（update_profile / change_password）自 2026-09-09 起仅限 Web 端，工具已移除，
此处同步收敛为两工具（"其他标签页仅限 Web"口径对齐）。

委托的审核/审计服务函数直接 patch（隔离 DB），会话经 patch get_session_factory
产出伪 session（get/flush/commit/rollback 可控）。
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
        assert skill.support("query_audit_logs") is True
        # 2026-09-09 起个人设置仅 Web，已移除工具不再支持
        assert skill.support("update_profile") is False
        assert skill.support("change_password") is False
        assert skill.support("execute_sql_text") is False

    def test_四工具齐备(self, skill):
        names = {m.tool_name for m in skill.list_tools()}
        assert names == {
            "review_skill", "query_audit_logs", "build_merge_version", "publish_merge_version",
        }

    def test_review仅admin其余全角色(self, skill):
        metas = {m.tool_name: m for m in skill.list_tools()}
        # §19.5.7：review_skill 仅 admin（对应 Web 审核弹窗双端承接）
        assert metas["review_skill"].roles == {"admin"}
        assert metas["query_audit_logs"].roles == {"admin", "developer", "user"}
        # merge 工作台双工具仅 admin（设计定稿④：试用与发布同一权限口径）
        assert metas["build_merge_version"].roles == {"admin"}
        assert metas["publish_merge_version"].roles == {"admin"}

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

    async def test_merge透传iteration_note与target_plaza_id(self, skill, mock_session):
        """工作台快捷通道：review_skill merge 携带 iteration_note / target_plaza_id（场景①）。"""
        result = make_review_result(action="review_merge", new_status="SHARE_ITERATION")
        with patch(f"{_AT}.SkillReviewService") as SvcCls:
            svc = SvcCls.return_value
            svc.review = AsyncMock(return_value=result)
            await skill.execute(
                "review_skill",
                {"skill_id": 9, "action": "merge", "iteration_note": "B 并入 A", "target_plaza_id": 66},
                make_context(ADMIN),
            )
        kwargs = svc.review.await_args.kwargs
        assert kwargs["iteration_note"] == "B 并入 A"
        assert kwargs["target_plaza_id"] == 66

    async def test_响应含产物补足提示(self, skill, mock_session):
        # 批次 5.1：review 响应含最新存档 generated_by + artifact_hint（template/model 级引导 CC 侧补足）
        result = make_review_result(action="review_approve")
        mock_session._exec_result.scalars.return_value.first.return_value = SimpleNamespace(
            generated_by="template"
        )
        with patch(f"{_AT}.SkillReviewService") as SvcCls:
            SvcCls.return_value.review = AsyncMock(return_value=result)
            res = await skill.execute(
                "review_skill", {"skill_id": 1, "action": "approve"}, make_context(ADMIN)
            )
        assert res["generated_by"] == "template"
        assert "submit_skill_artifact" in res["artifact_hint"]


# ==================== merge 工作台（设计定稿④，2026-09-10，仅 admin 委托 merge_service）====================


_MS = "platform_mcp.skills.merge_service"


def make_build_result(**kw) -> dict:
    defaults: dict = dict(
        merge_token="tok123", plaza_id=5, source_skills=[{"skill_id": 301, "role": "primary"}],
        base_version="1.0.0（当前）", new_version="1.0.1",
        conflicts=[{"path": "SKILL.md", "candidates": [], "default_source_skill_id": 301, "resolution": None}],
        audit_summary={"passed": True}, snapshot_path="/tmp/x", status="BUILT", created_by="admin",
        created_at=None,
    )
    defaults.update(kw)
    return defaults


class TestMergeWorkbenchTools:
    async def test_build委托merge_service(self, skill, mock_session):
        result = make_build_result()
        with patch(f"{_MS}.build_merge_version", new=AsyncMock(return_value=result)) as bm:
            res = await skill.execute(
                "build_merge_version",
                {"plaza_id": 5, "source_skill_ids": [301, 302], "base_version": None, "comment": "首次合并"},
                make_context(ADMIN),
            )
        assert res["success"] is True
        assert res["merge_token"] == "tok123"
        assert "试用" in res["message"]
        args, kwargs = bm.await_args
        assert args[0] is mock_session  # _session_scope 产出的会话直传服务
        assert kwargs["plaza_id"] == 5
        assert kwargs["source_skill_ids"] == [301, 302]
        assert kwargs["comment"] == "首次合并"
        assert kwargs["actor"].is_admin is True

    async def test_build参数校验缺plaza_id与空源被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("build_merge_version", {"source_skill_ids": [1]})
        with pytest.raises(SkillError):
            await skill.validate("build_merge_version", {"plaza_id": 5, "source_skill_ids": []})

    async def test_build_build合法参数通过(self, skill):
        params = {"plaza_id": 5, "source_skill_ids": [1, 2], "base_version": "1.0.0"}
        assert await skill.validate("build_merge_version", params) == params

    async def test_publish委托merge_service(self, skill, mock_session):
        result = make_build_result(status="PUBLISHED", conflicts=[], holders_marked=2)
        with patch(f"{_MS}.publish_merge_version", new=AsyncMock(return_value=result)) as pm:
            res = await skill.execute(
                "publish_merge_version",
                {"merge_token": "tok123", "action": "publish", "resolutions": {"SKILL.md": 302}},
                make_context(ADMIN),
            )
        assert res["status"] == "PUBLISHED" and res["holders_marked"] == 2
        assert "v1.0.1" in res["message"]
        args, kwargs = pm.await_args
        assert args[0] is mock_session
        assert kwargs["merge_token"] == "tok123"
        assert kwargs["action"] == "publish"
        assert kwargs["resolutions"] == {"SKILL.md": 302}

    async def test_publish_discard消息区分(self, skill, mock_session):
        result = {"merge_token": "tok123", "status": "DISCARDED"}
        with patch(f"{_MS}.publish_merge_version", new=AsyncMock(return_value=result)):
            res = await skill.execute(
                "publish_merge_version", {"merge_token": "tok123", "action": "discard"}, make_context(ADMIN)
            )
        assert res["status"] == "DISCARDED"
        assert "丢弃" in res["message"]

    async def test_publish参数校验缺token与非法action被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("publish_merge_version", {"action": "publish"})
        with pytest.raises(SkillError):
            await skill.validate("publish_merge_version", {"merge_token": "t", "action": "rollback"})

    async def test_服务错误码透传(self, skill, mock_session):
        with patch(
            f"{_MS}.publish_merge_version",
            new=AsyncMock(side_effect=SkillReviewError("该合并任务已终结", code=CODE_INVALID_STATE)),
        ):
            with pytest.raises(SkillReviewError) as ei:
                await skill.execute(
                    "publish_merge_version", {"merge_token": "tok", "action": "publish"}, make_context(ADMIN)
                )
        assert ei.value.error_code == CODE_INVALID_STATE


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
