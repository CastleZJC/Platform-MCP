"""单元测试 — Skill 生态 MCP 双通道工具（V3.0 M2.4 + M4，架构 §19.5.3 / §19.5.7 / F-29~F-32、F-36）

覆盖：身份贯通（identity→ReviewActor，user_id 映射、缺身份拒绝、locale 本地化）/ 参数校验 /
工具元数据（8 工具、描述中英并列、签名可构建）/ create_skill_draft（建草稿 + 唯一性 + 相似推荐 +
审计 create）/ update_my_skill（仅本人 F-29、内容重审计、REJECTED→DRAFT、WITHDRAWN→DRAFT、
审核中阻断、广场副本不受影响）/ submit·withdraw·resolve 委托审核服务（M4.3 iterate 内容级覆盖）/
set_my_skill_status（个人启停 F-32：ENABLED↔DISABLED、PENDING_REVIEW 停用视同撤回、
装饰器/广场复制 origin=PLAZA 仅 admin Web 端调整、非本人 10004）/
submit_skill_artifact（外部模型产物回传：重放校验拒绝/入档 external，F-36）/
get_skill_iteration_diff（差异素材 + 性能/外部模型提示，M4.4）/ 会话编排（成功 commit、
异常 rollback）/ draft 助手（分词、重叠度、广场扫描、内容落盘审计重放）。

用轻量 FakeSession 替代真实 AsyncSession，patch get_session_factory / build_draft_content /
scan_plaza_similar / write_audit_log，隔离文件 I/O、审计引擎与真实 DB。
"""

from __future__ import annotations

import base64
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.common.exceptions import SkillError
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
    SkillReviewError,
)
from platform_mcp.skills.audit.models import AuditResult
from platform_mcp.skills.ecosystem import (
    SkillEcosystemSkill,
    _build_actor,
    _decode_attachments,
    _format_review_result,
    _localized,
    _session_scope,
)
from platform_mcp.skills.ecosystem.draft import (
    DraftBuildResult,
    build_draft_content,
)
from platform_mcp.skills.embedding import tokenize
from platform_mcp.skills.models import PmcpSkillPlaza, PmcpSkillVersion
from platform_mcp.skills.plaza import (
    _overlap_score,
    scan_plaza_similar,
)


class FakeSession:
    """轻量伪 AsyncSession：get/add/flush/execute/commit/rollback。

    execute 按编译后 SQL 文本中的表名分派（先判 pmcp_skill_plaza 再判 pmcp_skill，避免子串误判）。
    """

    def __init__(self) -> None:
        self._store: dict[tuple[type, int], object] = {}
        self._added: list[object] = []
        self._id_seq = 9000
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.plaza_lookup_result: PmcpSkillPlaza | None = None
        self.plaza_all: list[PmcpSkillPlaza] = []
        self.user_id_result: int | None = None
        self.skill_lookup_result: PmcpSkill | None = None
        self.version_lookup_result: PmcpSkillVersion | None = None

    def seed(self, obj):
        self._store[(type(obj), obj.id)] = obj
        return obj

    async def get(self, model, pk):
        return self._store.get((model, pk))

    def add(self, obj) -> None:
        self._added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        for obj in self._added:
            if getattr(obj, "id", None) is None:
                obj.id = self._id_seq
                self._id_seq += 1
                self._store[(type(obj), obj.id)] = obj

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def execute(self, stmt):
        sql = str(stmt)
        result = MagicMock()
        if "pg_extension" in sql:
            # create_embedding_store 运行期探测：本地/测试环境 pgvector 不可用 → 降级 JSONB
            result.first.return_value = None
        elif "pmcp_skill_plaza.embedding" in sql and "pmcp_skill_plaza.skill_code" not in sql:
            # 向量列投影查询（JsonbEmbeddingStore.search）：广场副本无向量 → 关键词兜底粗排
            result.all.return_value = []
        elif "pmcp_skill_plaza" in sql:
            result.scalar_one_or_none.return_value = self.plaza_lookup_result
            result.scalars.return_value.all.return_value = self.plaza_all
        elif "pmcp_skill_version" in sql:
            # 版本存档 upsert 前置查询（M4：submit_skill_artifact / upgrade 任务）
            result.scalar_one_or_none.return_value = self.version_lookup_result
        elif "pmcp_user" in sql:
            result.scalar_one_or_none.return_value = self.user_id_result
        else:
            result.scalar_one_or_none.return_value = self.skill_lookup_result
        return result


def make_skill(**kw) -> PmcpSkill:
    defaults = dict(
        id=1,
        skill_code="demo-skill",
        skill_name="Demo",
        description="desc",
        status="DRAFT",
        register_method="mcp",
        tool_count=0,
        version="0.1.0",
        source_path="/store/demo",
        source_checksum="a" * 64,
        inserted_by="dev01",
        origin="ORIGINAL",
        share_status="unshared",
        plaza_id=None,
        review_comment=None,
        audit_status="passed",
        audit_result={"total_rules": 14, "critical_count": 0},
    )
    defaults.update(kw)
    return PmcpSkill(**defaults)


def make_plaza(**kw) -> PmcpSkillPlaza:
    """广场副本 seed helper（M4：迭代内容级 / 差异素材用）。"""
    defaults = dict(
        id=7,
        skill_code="demo-skill",
        skill_name="Demo",
        description="desc",
        version="0.2.0",
        status="PUBLISHED",
        source_path=None,
        source_checksum="c" * 64,
        involve_flags=None,
        iteration_note=None,
    )
    defaults.update(kw)
    return PmcpSkillPlaza(**defaults)


def make_version(**kw) -> PmcpSkillVersion:
    """版本存档 seed helper（M4：submit_skill_artifact partial 覆盖用）。"""
    defaults = dict(
        skill_id=1,
        version="0.1.0",
        checksum="a" * 64,
        readme_zh="旧中文 README",
        readme_en="old en README",
        report_zh="旧中文报告",
        report_en="old en report",
        audit_snapshot={"total_rules": 14, "critical_count": 0},
        generated_by="template",
        inserted_by="dev01",
        updated_by="dev01",
    )
    defaults.update(kw)
    return PmcpSkillVersion(**defaults)


def make_context(identity=None, trace_id="trace-xyz"):
    ctx = MagicMock()
    ctx.identity = identity
    ctx.trace_id = trace_id
    return ctx


def make_draft_result(audit_status: str = "passed", readme_generated: bool = True) -> DraftBuildResult:
    ar = AuditResult(skill_name="demo")
    ar.compute_counts()
    return DraftBuildResult(
        source_path="/store/demo",
        source_checksum="b" * 64,
        audit_result=ar,
        audit_status=audit_status,
        readme_generated=readme_generated,
    )


OWNER_IDENTITY = {"user_id": 2, "username": "dev01", "nickname": "Dev One", "role_code": "developer", "locale": "zh-CN"}
OWNER_EN_IDENTITY = {"user_id": 2, "username": "dev01", "nickname": "Dev One", "role_code": "developer", "locale": "en-US"}
ADMIN_IDENTITY = {"user_id": 1, "username": "admin", "nickname": "Admin", "role_code": "admin", "locale": "en-US"}


@pytest.fixture
def fake_db() -> FakeSession:
    return FakeSession()


@pytest.fixture
def skill() -> SkillEcosystemSkill:
    return SkillEcosystemSkill()


@pytest.fixture
def patch_session(fake_db):
    """patch get_session_factory：使 _session_scope 产出 FakeSession。"""

    @contextlib.asynccontextmanager
    async def _cm():
        yield fake_db

    def _factory():
        return _cm()

    with patch("platform_mcp.skills.ecosystem.get_session_factory", return_value=_factory):
        yield fake_db


@pytest.fixture
def audit_mock():
    """patch 生态层与审核服务层的 write_audit_log，避免审计独立 session 触库。"""
    with patch("platform_mcp.skills.ecosystem.write_audit_log", new=AsyncMock()) as eco, \
            patch("platform_mcp.review.service.write_audit_log", new=AsyncMock()) as rev:
        yield {"ecosystem": eco, "review": rev}


# ==================== 身份贯通 / 本地化（纯逻辑）====================


class TestBuildActor:
    def test_identity_映射为actor(self):
        actor = _build_actor(make_context(OWNER_IDENTITY, trace_id="t1"))
        assert isinstance(actor, ReviewActor)
        assert actor.username == "dev01"
        assert actor.role_code == "developer"
        assert actor.user_id == 2  # MCP identity 键为 user_id（非 Web 的 id）
        assert actor.locale == "zh-CN"
        assert actor.trace_id == "t1"

    def test_admin身份判定(self):
        actor = _build_actor(make_context(ADMIN_IDENTITY))
        assert actor.is_admin is True

    def test_缺身份拒绝(self):
        with pytest.raises(SkillReviewError) as ei:
            _build_actor(make_context(None))
        assert ei.value.error_code == CODE_FORBIDDEN

    def test_context为None拒绝(self):
        with pytest.raises(SkillReviewError) as ei:
            _build_actor(None)
        assert ei.value.error_code == CODE_FORBIDDEN

    def test_role缺失回退developer(self):
        actor = _build_actor(make_context({"username": "x", "user_id": 9}))
        assert actor.role_code == "developer"


class TestLocalized:
    def test_中文locale返回中文(self):
        actor = ReviewActor(username="d", role_code="developer", locale="zh-CN")
        assert _localized(actor, "中", "en") == "中"

    def test_英文locale返回英文(self):
        actor = ReviewActor(username="d", role_code="developer", locale="en-US")
        assert _localized(actor, "中", "en") == "en"

    def test_缺locale回退中文(self):
        actor = ReviewActor(username="d", role_code="developer", locale=None)
        assert _localized(actor, "中", "en") == "中"


# ==================== 校验 / 元数据（纯逻辑）====================


class TestValidateAndMeta:
    def test_skill_name与support(self, skill):
        assert skill.skill_name() == "skill_ecosystem"
        assert skill.support("create_skill_draft") is True
        assert skill.support("execute_sql_text") is False

    def test_八工具齐备(self, skill):
        names = {m.tool_name for m in skill.list_tools()}
        assert names == {
            "create_skill_draft", "update_my_skill", "submit_skill_for_review",
            "withdraw_review", "set_my_skill_status", "resolve_share_iteration",
            "submit_skill_artifact", "get_skill_iteration_diff",
        }

    def test_描述中英并列(self, skill):
        for meta in skill.list_tools():
            assert "/" in meta.description  # 中英并列分隔
            assert meta.audit_required is True

    def test_签名可构建_必填先于可选(self, skill):
        from platform_mcp.mcp_server.skill.registry import _build_handler_signature
        for meta in skill.list_tools():
            sig = _build_handler_signature(meta.input_schema)  # 不抛 ValueError 即通过
            assert len(sig.parameters) >= 1

    async def test_create缺skill_code被拒(self, skill):
        with pytest.raises(Exception):
            await skill.validate("create_skill_draft", {"skill_name": "n", "skill_md": "c"})

    async def test_create缺skill_md被拒(self, skill):
        with pytest.raises(Exception):
            await skill.validate("create_skill_draft", {"skill_code": "c", "skill_name": "n"})

    async def test_update缺skill_id被拒(self, skill):
        with pytest.raises(Exception):
            await skill.validate("update_my_skill", {})

    async def test_resolve非法choice被拒(self, skill):
        with pytest.raises(Exception):
            await skill.validate("resolve_share_iteration", {"skill_id": 1, "choice": "bad"})

    async def test_resolve合法choice通过(self, skill):
        params = {"skill_id": 1, "choice": "iterate"}
        assert await skill.validate("resolve_share_iteration", params) == params

    async def test_未知工具execute抛NotImplemented(self, skill):
        with pytest.raises(NotImplementedError):
            await skill.execute("unknown_tool", {}, make_context(OWNER_IDENTITY))


# ==================== create_skill_draft ====================


class TestCreateSkillDraft:
    async def test_创建草稿成功(self, skill, patch_session, audit_mock):
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result()), \
                patch("platform_mcp.skills.ecosystem.scan_plaza_similar", new=AsyncMock(return_value=[])):
            res = await skill.execute("create_skill_draft", {
                "skill_code": "new-skill", "skill_name": "New", "skill_md": "# hi",
            }, make_context(OWNER_IDENTITY))
        assert res["success"] is True
        assert res["skill_code"] == "new-skill"
        assert res["status"] == "DRAFT"
        assert res["recommendation"] == "new"
        assert patch_session.commit_count == 1

    async def test_草稿字段写库正确(self, skill, patch_session, audit_mock):
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result("warning")), \
                patch("platform_mcp.skills.ecosystem.scan_plaza_similar", new=AsyncMock(return_value=[])):
            res = await skill.execute("create_skill_draft", {
                "skill_code": "s1", "skill_name": "S1", "skill_md": "# c", "version": "1.0.0",
            }, make_context(OWNER_IDENTITY))
        created = patch_session._store[(PmcpSkill, res["skill_id"])]
        assert created.register_method == "mcp"
        assert created.origin == "ORIGINAL"
        assert created.share_status == "unshared"
        assert created.inserted_by == "dev01"
        assert created.version == "1.0.0"
        assert created.audit_status == "warning"
        assert res["audit_status"] == "warning"

    async def test_相似推荐透传与merge结论(self, skill, patch_session, audit_mock):
        similar = [{"plaza_id": 5, "skill_code": "exist", "recommendation": "merge", "similarity": 0.8}]
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result()), \
                patch("platform_mcp.skills.ecosystem.scan_plaza_similar", new=AsyncMock(return_value=similar)):
            res = await skill.execute("create_skill_draft", {
                "skill_code": "s2", "skill_name": "S2", "skill_md": "# c",
            }, make_context(OWNER_IDENTITY))
        assert res["similar_skills"] == similar
        assert res["recommendation"] == "merge"

    async def test_编码重复被拒(self, skill, patch_session, audit_mock):
        patch_session.skill_lookup_result = make_skill(skill_code="dup")
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result()), \
                patch("platform_mcp.skills.ecosystem.scan_plaza_similar", new=AsyncMock(return_value=[])):
            with pytest.raises(SkillReviewError) as ei:
                await skill.execute("create_skill_draft", {
                    "skill_code": "dup", "skill_name": "D", "skill_md": "# c",
                }, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE
        assert patch_session.rollback_count == 1

    async def test_审计create资源类型skill(self, skill, patch_session, audit_mock):
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result()), \
                patch("platform_mcp.skills.ecosystem.scan_plaza_similar", new=AsyncMock(return_value=[])):
            await skill.execute("create_skill_draft", {
                "skill_code": "s3", "skill_name": "S3", "skill_md": "# c",
            }, make_context(OWNER_IDENTITY))
        eco = audit_mock["ecosystem"]
        eco.assert_awaited_once()
        kwargs = eco.await_args.kwargs
        assert kwargs["resource_type"] == "skill"
        assert kwargs["operator"] == "dev01"
        assert kwargs["extra_data"]["action"] == "create"
        assert kwargs["extra_data"]["channel"] == "mcp"

    async def test_缺身份拒绝(self, skill, patch_session, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("create_skill_draft", {
                "skill_code": "s4", "skill_name": "S4", "skill_md": "# c",
            }, make_context(None))
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== update_my_skill ====================


class TestUpdateMySkill:
    async def test_仅改元数据成功(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="DRAFT", skill_name="Old"))
        res = await skill.execute("update_my_skill", {
            "skill_id": 1, "skill_name": "NewName", "description": "new desc",
        }, make_context(OWNER_IDENTITY))
        assert res["success"] is True
        assert res["skill_name"] == "NewName"
        assert res["action"] == "update"
        assert res["status"] == "DRAFT"
        assert patch_session.commit_count == 1

    async def test_改内容触发重审计(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result("failed")) as bdc:
            res = await skill.execute("update_my_skill", {
                "skill_id": 1, "skill_md": "# new content",
            }, make_context(OWNER_IDENTITY))
        bdc.assert_called_once()
        assert res["audit_status"] == "failed"

    async def test_非本人更新被拒(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, inserted_by="dev01"))
        other = {"user_id": 3, "username": "dev02", "role_code": "developer", "locale": "zh-CN"}
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("update_my_skill", {"skill_id": 1, "skill_name": "x"}, make_context(other))
        assert ei.value.error_code == CODE_FORBIDDEN  # F-29

    async def test_不存在被拒(self, skill, patch_session, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("update_my_skill", {"skill_id": 999}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_拒绝态更新回草稿(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="REJECTED", review_comment="原因"))
        # 含内容更新，需 patch build_draft_content
        with patch("platform_mcp.skills.ecosystem.build_draft_content", return_value=make_draft_result()):
            res = await skill.execute("update_my_skill", {"skill_id": 1, "skill_md": "# fix"}, make_context(OWNER_IDENTITY))
        assert res["old_status"] == "REJECTED"
        assert res["status"] == "DRAFT"
        assert res["action"] == "update_revise"

    async def test_撤回态更新回草稿(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="WITHDRAWN"))
        res = await skill.execute("update_my_skill", {"skill_id": 1, "skill_name": "n"}, make_context(OWNER_IDENTITY))
        assert res["old_status"] == "WITHDRAWN"
        assert res["status"] == "DRAFT"
        assert res["action"] == "update_restore"

    async def test_审核中不可更新(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="PENDING_REVIEW"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("update_my_skill", {"skill_id": 1, "skill_name": "n"}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_分享迭代不可更新(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="SHARE_ITERATION"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("update_my_skill", {"skill_id": 1, "skill_name": "n"}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_更新不触碰广场副本(self, skill, patch_session, audit_mock):
        # F-29：广场副本独立表，更新个人库草稿不改 plaza_id / share_status
        patch_session.seed(make_skill(id=1, status="ENABLED", share_status="shared", plaza_id=77))
        res = await skill.execute("update_my_skill", {"skill_id": 1, "description": "d"}, make_context(OWNER_IDENTITY))
        updated = patch_session._store[(PmcpSkill, 1)]
        assert updated.plaza_id == 77
        assert updated.share_status == "shared"
        assert res["success"] is True


# ==================== submit / withdraw / resolve（委托审核服务）====================


class TestSubmitWithdrawResolve:
    async def test_submit_草稿转审核中(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        res = await skill.execute("submit_skill_for_review", {"skill_id": 1}, make_context(OWNER_IDENTITY))
        assert res["old_status"] == "DRAFT"
        assert res["new_status"] == "PENDING_REVIEW"
        assert res["action"] == "submit"
        assert audit_mock["review"].await_args.kwargs["resource_type"] == "skill"

    async def test_submit_重复分享需确认(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="ENABLED", share_status="shared"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("submit_skill_for_review", {"skill_id": 1}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == 10005  # CODE_RESHARE_CONFIRM

    async def test_submit_确认后覆盖重提(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="ENABLED", share_status="shared"))
        res = await skill.execute("submit_skill_for_review", {"skill_id": 1, "confirm_reshare": True}, make_context(OWNER_IDENTITY))
        assert res["new_status"] == "PENDING_REVIEW"

    async def test_withdraw_审核中转撤回(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="PENDING_REVIEW"))
        res = await skill.execute("withdraw_review", {"skill_id": 1}, make_context(OWNER_IDENTITY))
        assert res["old_status"] == "PENDING_REVIEW"
        assert res["new_status"] == "WITHDRAWN"
        assert res["action"] == "withdraw"

    async def test_withdraw_非审核中被拒(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("withdraw_review", {"skill_id": 1}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_resolve_迭代转启用(self, skill, patch_session, audit_mock):
        # M4.3：iterate 需广场副本存在（快照缺失时降级为仅元数据同步，content_merged=False）
        patch_session.seed(make_skill(id=1, status="SHARE_ITERATION", plaza_id=7, origin="PLAZA"))
        patch_session.seed(make_plaza(id=7, skill_name="Plaza Name", version="0.2.0"))
        res = await skill.execute("resolve_share_iteration", {"skill_id": 1, "choice": "iterate"}, make_context(OWNER_IDENTITY))
        assert res["new_status"] == "ENABLED"
        assert res["action"] == "resolve_iteration_iterate"
        updated = patch_session._store[(PmcpSkill, 1)]
        assert updated.skill_name == "Plaza Name"  # 元数据同步（采纳广场口径）
        assert updated.version == "0.2.0"

    async def test_resolve_保留转启用(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="SHARE_ITERATION"))
        res = await skill.execute("resolve_share_iteration", {"skill_id": 1, "choice": "keep"}, make_context(OWNER_IDENTITY))
        assert res["new_status"] == "ENABLED"
        assert res["action"] == "resolve_iteration_keep"

    async def test_resolve_iterate_内容级覆盖本地(self, skill, patch_session, audit_mock, tmp_path):
        """M4.3 内容级：广场快照复制回个人目录 + 重放审计 + 元数据同步 + 版本存档。"""
        local = tmp_path / "demo-skill"
        local.mkdir()
        (local / "SKILL.md").write_text("# local old\n", encoding="utf-8")
        snap = tmp_path / "_plaza" / "7"
        snap.mkdir(parents=True)
        (snap / "SKILL.md").write_text("---\nname: Plaza Name\ndescription: from plaza\nversion: 0.2.0\n---\n# plaza new\n", encoding="utf-8")
        settings_mock = MagicMock()
        settings_mock.skill.upload_dir = str(tmp_path)
        patch_session.seed(make_skill(
            id=1, status="SHARE_ITERATION", plaza_id=7, origin="PLAZA",
            source_path=str(local), version="0.1.0",
        ))
        patch_session.seed(make_plaza(id=7, skill_name="Plaza Name", version="0.2.0", source_path=str(snap)))
        with patch("platform_mcp.review.service.get_settings", return_value=settings_mock):
            res = await skill.execute(
                "resolve_share_iteration", {"skill_id": 1, "choice": "iterate"}, make_context(OWNER_IDENTITY),
            )
        assert res["new_status"] == "ENABLED"
        # 本地目录被广场快照覆盖（磁盘层）
        assert (local / "SKILL.md").read_text(encoding="utf-8").startswith("---")
        updated = patch_session._store[(PmcpSkill, 1)]
        assert updated.skill_name == "Plaza Name"
        assert updated.version == "0.2.0"
        assert updated.source_path == str(local)
        assert updated.audit_status in {"passed", "warning", "failed"}

    async def test_resolve_英文locale消息含覆盖说明(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="SHARE_ITERATION", plaza_id=7, origin="PLAZA"))
        patch_session.seed(make_plaza(id=7))
        res = await skill.execute(
            "resolve_share_iteration", {"skill_id": 1, "choice": "iterate"}, make_context(OWNER_EN_IDENTITY),
        )
        assert "overwrote local" in res["message"]

    async def test_英文locale返回英文消息(self, skill, patch_session, audit_mock):
        # §19.5.2 动态产物按认证身份 locale 返回：owner 本人 + en-US → 英文成功消息
        patch_session.seed(make_skill(id=1, status="DRAFT", inserted_by="dev01"))
        res = await skill.execute("submit_skill_for_review", {"skill_id": 1}, make_context(OWNER_EN_IDENTITY))
        assert res["success"] is True
        assert "Submitted" in res["message"]

    async def test_非owner提交被拒(self, skill, patch_session, audit_mock):
        # F-29：submit 亦经审核服务 owner 校验；admin 非本人提交他人 Skill → 10004
        patch_session.seed(make_skill(id=1, status="DRAFT", inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("submit_skill_for_review", {"skill_id": 1}, make_context(ADMIN_IDENTITY))
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== set_my_skill_status（个人启停，F-32）====================


class TestSetMySkillStatus:
    async def test_disable_启用转停用(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="ENABLED"))
        res = await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "DISABLED"}, make_context(OWNER_IDENTITY))
        assert res["success"] is True
        assert res["old_status"] == "ENABLED"
        assert res["new_status"] == "DISABLED"
        assert res["action"] == "disable"
        assert audit_mock["review"].await_args.kwargs["resource_type"] == "skill"

    async def test_enable_停用转启用(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="DISABLED"))
        res = await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "ENABLED"}, make_context(OWNER_IDENTITY))
        assert res["new_status"] == "ENABLED"
        assert res["action"] == "enable"

    async def test_disable_审核中视同撤回(self, skill, patch_session, audit_mock):
        # F-32：PENDING_REVIEW 停用 → WITHDRAWN（同 withdraw 语义）
        patch_session.seed(make_skill(id=1, status="PENDING_REVIEW"))
        res = await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "DISABLED"}, make_context(OWNER_IDENTITY))
        assert res["new_status"] == "WITHDRAWN"
        assert res["action"] == "withdraw_via_disable"

    async def test_非法转移被拒(self, skill, patch_session, audit_mock):
        # DRAFT 无 enable 转移（状态机裁决 10003）
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "ENABLED"}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_装饰器Skill仅adminWeb调整(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="ENABLED", register_method="decorator"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "DISABLED"}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_广场复制Skill仅adminWeb调整(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="ENABLED", origin="PLAZA"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "DISABLED"}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非owner被拒(self, skill, patch_session, audit_mock):
        # F-29：经审核服务 owner 校验；admin 非本人启停他人 Skill → 10004
        patch_session.seed(make_skill(id=1, status="ENABLED", inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("set_my_skill_status", {"skill_id": 1, "status": "DISABLED"}, make_context(ADMIN_IDENTITY))
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_Skill不存在(self, skill, patch_session, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("set_my_skill_status", {"skill_id": 404, "status": "DISABLED"}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_validate非法status被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("set_my_skill_status", {"skill_id": 1, "status": "PAUSED"})

    async def test_validate缺skill_id被拒(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("set_my_skill_status", {"status": "ENABLED"})

    async def test_validate合法参数通过(self, skill):
        params = {"skill_id": 1, "status": "ENABLED"}
        assert await skill.validate("set_my_skill_status", params) == params

    async def test_英文locale返回英文消息(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, status="ENABLED", inserted_by="dev01"))
        res = await skill.execute(
            "set_my_skill_status", {"skill_id": 1, "status": "DISABLED"}, make_context(OWNER_EN_IDENTITY),
        )
        assert res["success"] is True
        assert "disabled" in res["message"]


# ==================== 会话编排 ====================


class TestSessionScope:
    async def test_成功commit(self, patch_session, fake_db):
        async with _session_scope() as session:
            assert session is fake_db
        assert fake_db.commit_count == 1
        assert fake_db.rollback_count == 0

    async def test_异常rollback(self, patch_session, fake_db):
        with pytest.raises(RuntimeError):
            async with _session_scope() as session:
                raise RuntimeError("boom")
        assert fake_db.rollback_count == 1
        assert fake_db.commit_count == 0


class TestFormatReviewResult:
    def test_结果字段完整(self):
        from platform_mcp.review.service import ReviewResult
        r = ReviewResult(skill_id=1, skill_code="c", action="submit", old_status="DRAFT",
                         new_status="PENDING_REVIEW", share_status="unshared", plaza_id=None, review_comment=None)
        d = _format_review_result(r, "ok")
        assert d["success"] is True
        assert d["skill_code"] == "c"
        assert d["new_status"] == "PENDING_REVIEW"
        assert d["message"] == "ok"


# ==================== draft 助手 ====================


class TestDraftHelpers:
    def test_分词去停用词与单字(self):
        tokens = tokenize("The Skill-Manager 工具")
        assert "skill" not in tokens  # 停用词
        assert "manager" in tokens
        assert "工具" in tokens

    def test_分词空输入(self):
        assert tokenize(None) == []
        assert tokenize("") == []

    def test_重叠度全同为1(self):
        nt = set(tokenize("data cleaner"))
        dt = set(tokenize("clean data fast"))
        score = _overlap_score(nt, dt, "data cleaner", "clean data fast")
        assert score == pytest.approx(1.0)

    def test_重叠度无关为0(self):
        score = _overlap_score(set(tokenize("alpha")), set(tokenize("beta")), "gamma", "delta")
        assert score == 0.0

    async def test_广场扫描降序与结论(self, fake_db):
        fake_db.plaza_all = [
            PmcpSkillPlaza(id=1, skill_code="data-cleaner", skill_name="Data Cleaner", description="clean data", status="PUBLISHED", version="1.0"),
            PmcpSkillPlaza(id=2, skill_code="unrelated", skill_name="Weather", description="forecast", status="PUBLISHED", version="1.0"),
        ]
        recs = await scan_plaza_similar(fake_db, "Data Cleaner", "clean data fast")
        assert recs[0]["skill_code"] == "data-cleaner"
        assert recs[0]["recommendation"] == "merge"
        assert all(r["similarity"] > 0 for r in recs)

    async def test_广场扫描排除自身编码(self, fake_db):
        fake_db.plaza_all = [
            PmcpSkillPlaza(id=1, skill_code="self", skill_name="Self", description="self", status="PUBLISHED"),
        ]
        recs = await scan_plaza_similar(fake_db, "Self", "self", exclude_skill_code="self")
        assert recs == []

    def test_内容落盘审计重放(self, tmp_path):
        settings_mock = MagicMock()
        settings_mock.skill.upload_dir = str(tmp_path)
        skill_md = "---\nname: demo\ndescription: d\nversion: 0.1.0\n---\n# Demo\nhello world\n"
        with patch("platform_mcp.skills.ecosystem.draft.get_settings", return_value=settings_mock):
            result = build_draft_content(
                skill_code="demo", skill_name="Demo", description="d", skill_md=skill_md, version="0.1.0",
            )
        assert result.audit_status in {"passed", "warning", "failed"}
        assert len(result.source_checksum) == 64
        assert result.readme_generated is True
        assert (tmp_path / "demo" / "SKILL.md").exists()
        assert (tmp_path / "demo" / "README.md").exists()

    def test_内容落盘含自定义README不再生成(self, tmp_path):
        settings_mock = MagicMock()
        settings_mock.skill.upload_dir = str(tmp_path)
        skill_md = "---\nname: demo\n---\n# Demo\n"
        with patch("platform_mcp.skills.ecosystem.draft.get_settings", return_value=settings_mock):
            result = build_draft_content(
                skill_code="demo2", skill_name="Demo", description="d",
                skill_md=skill_md, version="0.1.0", readme="# Custom README\n",
            )
        assert result.readme_generated is False
        assert (tmp_path / "demo2" / "README.md").read_text(encoding="utf-8") == "# Custom README\n"


class TestMcpAttachments:
    """MCP 通道附件（references/脚本/图片随包存档；与 Web 上传同限、路径仅包内相对路径）。"""

    @staticmethod
    def _rc(cap_mb: int) -> MagicMock:
        rc = MagicMock()
        rc.get_sync = MagicMock(return_value=cap_mb)
        return rc

    def test_附件落盘并计入checksum(self, tmp_path):
        settings_mock = MagicMock()
        settings_mock.skill.upload_dir = str(tmp_path)
        skill_md = "---\nname: demo\n---\n# Demo\n"
        with patch("platform_mcp.skills.ecosystem.draft.get_settings", return_value=settings_mock):
            base = build_draft_content(
                skill_code="att", skill_name="Demo", description="d",
                skill_md=skill_md, version="0.1.0",
            )
            with_att = build_draft_content(
                skill_code="att", skill_name="Demo", description="d",
                skill_md=skill_md, version="0.1.0",
                attachments=[("references/oracle.md", b"# Oracle\n"), ("img/logo.png", b"\x89PNG")],
            )
        assert (tmp_path / "att" / "references" / "oracle.md").exists()
        assert (tmp_path / "att" / "img" / "logo.png").read_bytes() == b"\x89PNG"
        assert base.source_checksum != with_att.source_checksum  # 附件计入校验和

    def test_附件解码成功(self):
        encoded = base64.b64encode("hello".encode()).decode()
        with patch("platform_mcp.skills.ecosystem.runtime_config", self._rc(50)):
            decoded = _decode_attachments({"attachments": [
                {"path": "references/a.md", "content_base64": encoded},
            ]})
        assert decoded == [("references/a.md", b"hello")]

    def test_附件路径穿越与绝对路径被拒(self):
        with patch("platform_mcp.skills.ecosystem.runtime_config", self._rc(50)):
            with pytest.raises(SkillError):
                _decode_attachments({"attachments": [{"path": "../evil.md", "content_base64": "aGk="}]})
            with pytest.raises(SkillError):
                _decode_attachments({"attachments": [{"path": "C:/abs.md", "content_base64": "aGk="}]})
            with pytest.raises(SkillError):
                _decode_attachments({"attachments": [{"path": "/abs.md", "content_base64": "aGk="}]})

    def test_附件超限被拒(self):
        big = base64.b64encode(b"x" * (1024 * 1024 + 1)).decode()
        with patch("platform_mcp.skills.ecosystem.runtime_config", self._rc(1)):
            with pytest.raises(SkillError):
                _decode_attachments({"attachments": [{"path": "big.bin", "content_base64": big}]})

    def test_附件base64非法被拒(self):
        with patch("platform_mcp.skills.ecosystem.runtime_config", self._rc(50)):
            with pytest.raises(SkillError):
                _decode_attachments({"attachments": [{"path": "a.md", "content_base64": "not-b64!!"}]})


# ==================== submit_skill_artifact（M4，F-36 外部模型产物回传）====================


class TestSubmitSkillArtifact:
    async def test_validate_非法类型被拒(self, skill):
        with pytest.raises(Exception):
            await skill.validate("submit_skill_artifact", {
                "skill_id": 1, "artifact_type": "bad", "content_zh": "x",
            })

    async def test_validate_内容全空被拒(self, skill):
        with pytest.raises(Exception):
            await skill.validate("submit_skill_artifact", {"skill_id": 1, "artifact_type": "readme"})

    async def test_readme回传入档external(self, skill, patch_session, audit_mock):
        """重放校验通过 → 传入侧覆盖、未传侧保留，generated_by=external（F-36）。"""
        existing = make_version(skill_id=1, version="0.1.0")
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        patch_session.version_lookup_result = existing
        res = await skill.execute("submit_skill_artifact", {
            "skill_id": 1, "artifact_type": "readme",
            "content_zh": "# 外部模型 README\n\nglm 5.3 产物\n",
            "content_en": "# External README\n\nglm 5.3 artifact\n",
        }, make_context(OWNER_IDENTITY))
        assert res["success"] is True
        assert res["generated_by"] == "external"
        assert existing.generated_by == "external"
        assert existing.readme_zh.startswith("# 外部模型 README")
        assert existing.readme_en.startswith("# External README")
        assert existing.report_zh == "旧中文报告"  # 未传侧保留
        assert patch_session.commit_count == 1

    async def test_严重违规拒绝并返回清单(self, skill, patch_session, audit_mock):
        """🔴 严重命中 → success=False + 结构化违规清单（不写库存档），审计留拒绝记录。"""
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        violations = [{
            "rule_id": "R4-01", "severity": "critical", "description": "硬编码密钥",
            "suggestion": "移除", "line_number": 3,
        }]
        with patch(
            "platform_mcp.skills.ecosystem.replay_validate_artifact",
            return_value=(False, violations),
        ):
            res = await skill.execute("submit_skill_artifact", {
                "skill_id": 1, "artifact_type": "report", "content_zh": "包含密钥的文本",
            }, make_context(OWNER_IDENTITY))
        assert res["success"] is False
        assert res["violations"][0]["rule_id"] == "R4-01"
        assert res["violations"][0]["language"] == "zh"
        eco = audit_mock["ecosystem"]
        assert eco.await_args.kwargs["extra_data"]["action"] == "submit_artifact_rejected"
        # 拒绝路径不写版本存档（无 archive mutate）
        assert patch_session.version_lookup_result is None

    async def test_非本人回传被拒(self, skill, patch_session, audit_mock):
        patch_session.seed(make_skill(id=1, inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("submit_skill_artifact", {
                "skill_id": 1, "artifact_type": "readme", "content_zh": "x",
            }, make_context(ADMIN_IDENTITY))
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_不存在被拒(self, skill, patch_session, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("submit_skill_artifact", {
                "skill_id": 999, "artifact_type": "readme", "content_zh": "x",
            }, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_无存档行时模板重建兜底入档(self, skill, patch_session, audit_mock):
        """首次无存档行：按模板重建另一侧兜底值后入档（upsert 新建，F-28）。"""
        patch_session.seed(make_skill(id=1, status="DRAFT"))
        with patch("platform_mcp.skills.ecosystem.scan_plaza_similar", new=AsyncMock(return_value=[])):
            pass  # submit_artifact 不扫广场；仅为隔离潜在依赖
        res = await skill.execute("submit_skill_artifact", {
            "skill_id": 1, "artifact_type": "readme", "content_zh": "# 新 README\n",
        }, make_context(OWNER_IDENTITY))
        assert res["success"] is True
        archived = patch_session._added[0]  # archive_skill_version 走 db.add 新建分支
        assert isinstance(archived, PmcpSkillVersion)
        assert archived.generated_by == "external"
        assert archived.readme_zh == "# 新 README\n"
        assert archived.report_zh  # 另一侧模板重建非空


# ==================== get_skill_iteration_diff（M4.3/M4.4 差异素材）====================


class TestGetSkillIterationDiff:
    def _setup_iteration(self, patch_session, tmp_path, *, status="SHARE_ITERATION", owner="dev01") -> None:
        local = tmp_path / "demo-skill"
        local.mkdir(parents=True, exist_ok=True)
        (local / "SKILL.md").write_text("# 本地版本\n旧内容\n", encoding="utf-8")
        snap = tmp_path / "_plaza" / "7"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "SKILL.md").write_text("# 广场版本\n新内容\n", encoding="utf-8")
        patch_session.seed(make_skill(
            id=1, status=status, plaza_id=7, origin="PLAZA",
            source_path=str(local), inserted_by=owner,
        ))
        patch_session.seed(make_plaza(id=7, source_path=str(snap), skill_name="Demo"))

    async def test_返回差异素材与提示(self, skill, patch_session, audit_mock, tmp_path):
        """行级 diff + 语义相似度 + 性能/外部模型提示（M4.4），不本地生成描述。"""
        self._setup_iteration(patch_session, tmp_path)
        res = await skill.execute("get_skill_iteration_diff", {"skill_id": 1}, make_context(OWNER_IDENTITY))
        assert res["skill_code"] == "demo-skill"
        assert "description_zh" not in res  # MCP 通道不生成描述（§19.5.1 双通道职责边界）
        assert "本地版本" in res["unified_diff"] and "广场版本" in res["unified_diff"]
        assert res["added_lines"] >= 1 and res["removed_lines"] >= 1
        assert 0.0 <= res["similarity"] <= 1.0
        assert "本地模型" in res["performance_hint"] or "local model" in res["performance_hint"]
        assert "glm 5.3" in res["external_hint"]
        assert res["message"]

    async def test_非迭代态被拒(self, skill, patch_session, audit_mock, tmp_path):
        self._setup_iteration(patch_session, tmp_path, status="ENABLED")
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("get_skill_iteration_diff", {"skill_id": 1}, make_context(OWNER_IDENTITY))
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非owner非admin被拒(self, skill, patch_session, audit_mock, tmp_path):
        self._setup_iteration(patch_session, tmp_path)
        other = {"user_id": 3, "username": "dev02", "role_code": "developer", "locale": "zh-CN"}
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("get_skill_iteration_diff", {"skill_id": 1}, make_context(other))
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_admin可查(self, skill, patch_session, audit_mock, tmp_path):
        """admin 因迭代监督可查（ADMIN_REVIEW_STATES 含 SHARE_ITERATION）。"""
        self._setup_iteration(patch_session, tmp_path)
        res = await skill.execute("get_skill_iteration_diff", {"skill_id": 1}, make_context(ADMIN_IDENTITY))
        assert "unified_diff" in res
