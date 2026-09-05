"""单元测试 — 可复用审核服务（V3.0 M2 + M4.3，架构 §19.5.3 / F-26~F-32、F-40、F-30 内容级）

覆盖：提交分享（含 F-31 重复分享二次确认）/ admin 审核（approve 新增入广场 + 广场副本 upsert +
M4.3 快照 / merge 合并迭代 + 内容级同步 / reject 拒绝存原因）/ 撤回 / 分享迭代解决（F-30，
iterate 内容级覆盖）/ 修改重编辑 / 恢复 / 启停（含 F-32 停用视同撤回）/ 归属与权限校验（F-29 不能
操作他人）/ 可见性矩阵（F-27）/ 审计留痕可区分（F-40）/ 事务边界（mutate+flush 不 commit）/
M4.3 快照助手与差异查询（build_iteration_diff 权限/状态）。

用轻量 FakeSession 替代真实 AsyncSession（按 SQL 文本表名分派 execute 结果），
并 patch write_audit_log 避免审计独立 session 触库。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    CODE_RESHARE_CONFIRM,
    ReviewActor,
    SkillReviewError,
    SkillReviewService,
)
from platform_mcp.skills.models import PmcpSkillPlaza
from platform_mcp.review.service import restore_snapshot_to_local, snapshot_plaza_source


class FakeSession:
    """轻量伪 AsyncSession：仅实现审核服务用到的 get/add/flush/execute。

    - ``get(model, pk)``：从内存 store 取；
    - ``add`` + ``flush``：为无 id 的新对象分配自增 id 并入 store（模拟广场副本插入）；
    - ``execute(stmt)``：按编译后 SQL 文本中的表名分派可配置的 ``scalar_one_or_none`` 结果。
    未定义 ``commit``——服务若误调用即抛 AttributeError，佐证"mutate+flush 不 commit"。
    """

    def __init__(self) -> None:
        self._store: dict[tuple[type, int], object] = {}
        self._added: list[object] = []
        self._id_seq = 9000
        self.flush_count = 0
        self.plaza_lookup_result: PmcpSkillPlaza | None = None
        self.user_id_result: int | None = None
        self.executed_sql: list[str] = []

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

    async def execute(self, stmt):
        sql = str(stmt)
        self.executed_sql.append(sql)
        result = MagicMock()
        if "pmcp_skill_plaza" in sql:
            result.scalar_one_or_none.return_value = self.plaza_lookup_result
        elif "pmcp_user" in sql:
            result.scalar_one_or_none.return_value = self.user_id_result
        else:
            result.scalar_one_or_none.return_value = None
        return result


def make_skill(**kw) -> PmcpSkill:
    """构造一个 PmcpSkill ORM 实例（不触库，仅属性访问）。"""
    defaults = dict(
        id=1,
        skill_code="demo-skill",
        skill_name="Demo",
        description="desc",
        status="DRAFT",
        register_method="upload",
        tool_count=0,
        version="0.1.0",
        source_path="/store/demo",
        source_checksum="abc123",
        inserted_by="dev01",
        origin="ORIGINAL",
        share_status="unshared",
        plaza_id=None,
        review_comment=None,
    )
    defaults.update(kw)
    return PmcpSkill(**defaults)


@pytest.fixture
def fake_db() -> FakeSession:
    return FakeSession()


@pytest.fixture
def service(fake_db) -> SkillReviewService:
    return SkillReviewService(fake_db)


@pytest.fixture
def owner() -> ReviewActor:
    return ReviewActor(username="dev01", role_code="developer", user_id=2)


@pytest.fixture
def admin() -> ReviewActor:
    return ReviewActor(username="admin", role_code="admin", user_id=1)


@pytest.fixture
def other_dev() -> ReviewActor:
    return ReviewActor(username="dev02", role_code="developer", user_id=3)


@pytest.fixture
def audit_mock():
    with patch("platform_mcp.review.service.write_audit_log", new=AsyncMock()) as m:
        yield m


# ==================== 提交分享（含 F-31 重复分享）====================


class TestSubmitForReview:
    async def test_草稿提交转审核中(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="DRAFT"))
        res = await service.submit_for_review(owner, skill.id)
        assert skill.status == "PENDING_REVIEW"
        assert res.old_status == "DRAFT"
        assert res.new_status == "PENDING_REVIEW"
        assert res.action == "submit"

    async def test_未分享已启用可再提交(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="ENABLED", share_status="unshared"))
        res = await service.submit_for_review(owner, skill.id)
        assert skill.status == "PENDING_REVIEW"
        assert res.action == "submit"

    async def test_提交写审计且资源类型为skill(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="DRAFT"))
        await service.submit_for_review(owner, skill.id)
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs["resource_type"] == "skill"
        assert kwargs["operator"] == "dev01"
        assert kwargs["extra_data"]["action"] == "submit"
        assert kwargs["extra_data"]["old_status"] == "DRAFT"
        assert kwargs["extra_data"]["new_status"] == "PENDING_REVIEW"

    async def test_提交后flush不commit(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="DRAFT"))
        await service.submit_for_review(owner, skill.id)
        assert fake_db.flush_count >= 1
        assert skill.updated_by == "dev01"

    async def test_非本人提交被拒(self, service, fake_db, other_dev, audit_mock):
        fake_db.seed(make_skill(status="DRAFT", inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await service.submit_for_review(other_dev, 1)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_已拒绝不可直接提交须先修改(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="REJECTED"))
        with pytest.raises(SkillReviewError) as ei:
            await service.submit_for_review(owner, 1)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_重复分享未确认被拒(self, service, fake_db, owner, audit_mock):
        # F-31：已入广场（share_status=shared）再提交须二次确认
        fake_db.seed(make_skill(status="ENABLED", share_status="shared"))
        with pytest.raises(SkillReviewError) as ei:
            await service.submit_for_review(owner, 1)
        assert ei.value.error_code == CODE_RESHARE_CONFIRM

    async def test_重复分享确认后覆盖重提(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="ENABLED", share_status="shared"))
        res = await service.submit_for_review(owner, skill.id, confirm_reshare=True)
        assert skill.status == "PENDING_REVIEW"
        assert res.action == "submit"

    async def test_审核中重复分享未确认被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="PENDING_REVIEW"))
        with pytest.raises(SkillReviewError) as ei:
            await service.submit_for_review(owner, 1)
        assert ei.value.error_code == CODE_RESHARE_CONFIRM

    async def test_审核中重复分享确认状态不变(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", share_status="shared"))
        res = await service.submit_for_review(owner, skill.id, confirm_reshare=True)
        assert skill.status == "PENDING_REVIEW"
        assert res.action == "reshare"
        assert res.old_status == "PENDING_REVIEW"


# ==================== admin 审核（approve / merge / reject）====================


class TestAdminReview:
    async def test_approve_新增入广场并启用(self, service, fake_db, admin, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", inserted_by="dev01"))
        fake_db.user_id_result = 2
        res = await service.review(admin, skill.id, "approve", comment="LGTM")
        assert skill.status == "ENABLED"
        assert skill.share_status == "shared"
        assert skill.review_comment == "LGTM"
        assert skill.plaza_id is not None
        assert res.old_status == "PENDING_REVIEW"
        assert res.new_status == "ENABLED"
        assert res.action == "review_approve"

    async def test_approve_创建广场副本字段正确(self, service, fake_db, admin, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", skill_code="sc", version="1.2.3"))
        fake_db.user_id_result = 42
        await service.review(admin, skill.id, "approve")
        plaza = fake_db._store[(PmcpSkillPlaza, skill.plaza_id)]
        assert plaza.skill_code == "sc"
        assert plaza.version == "1.2.3"
        assert plaza.uploader_id == 42
        assert plaza.status == "PUBLISHED"
        assert plaza.inserted_by == "admin"

    async def test_approve_已存在广场副本则更新不新建(self, service, fake_db, admin, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", skill_code="dup", version="2.0.0"))
        existing = PmcpSkillPlaza(id=77, skill_code="dup", skill_name="Old", status="PUBLISHED", version="0.0.1")
        fake_db.seed(existing)
        fake_db.plaza_lookup_result = existing
        await service.review(admin, skill.id, "approve")
        assert skill.plaza_id == 77
        assert existing.version == "2.0.0"
        assert existing.updated_by == "admin"
        assert fake_db._id_seq == 9000  # 未分配新 id → 未新建副本

    async def test_approve_审计动作可区分(self, service, fake_db, admin, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW"))
        await service.review(admin, skill.id, "approve", comment="ok")
        kwargs = audit_mock.await_args.kwargs
        assert kwargs["extra_data"]["action"] == "review_approve"
        assert kwargs["extra_data"]["plaza_skill_code"] == skill.skill_code

    async def test_merge_源自广场转分享迭代(self, service, fake_db, admin, audit_mock):
        plaza = PmcpSkillPlaza(id=55, skill_code="pl", skill_name="PL", status="PUBLISHED")
        fake_db.seed(plaza)
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", origin="PLAZA", plaza_id=55, skill_code="pl"))
        res = await service.review(admin, skill.id, "merge", iteration_note="合并到 v2")
        assert skill.status == "SHARE_ITERATION"
        assert plaza.iteration_note == "合并到 v2"
        assert skill.review_comment == "合并到 v2"
        assert res.action == "review_merge"

    async def test_merge_内容级同步广场字段(self, service, fake_db, admin, audit_mock, tmp_path):
        """M4.3：merge 后提审内容采纳入广场（字段 + 涉库标记 + 快照路径）。"""
        local = tmp_path / "pl"
        local.mkdir()
        (local / "SKILL.md").write_text("# v2 content\n", encoding="utf-8")
        settings_mock = MagicMock()
        settings_mock.skill.upload_dir = str(tmp_path)
        plaza = PmcpSkillPlaza(id=55, skill_code="pl", skill_name="Old Name", version="1.0", status="PUBLISHED")
        fake_db.seed(plaza)
        skill = fake_db.seed(make_skill(
            status="PENDING_REVIEW", origin="PLAZA", plaza_id=55, skill_code="pl",
            skill_name="New Name", version="2.0", source_path=str(local),
            audit_result={"failed_rules": [{"rule_id": "R2-01", "severity": "critical"}]},
        ))
        with patch("platform_mcp.review.service.get_settings", return_value=settings_mock):
            await service.review(admin, skill.id, "merge", iteration_note="采纳 v2")
        assert plaza.skill_name == "New Name"          # 字段同步
        assert plaza.version == "2.0"
        assert "database" in (plaza.involve_flags or [])  # 涉库标记刷新（R2-xx）
        assert plaza.source_path and "_plaza" in plaza.source_path.replace("\\", "/")  # 快照路径
        assert Path(plaza.source_path).is_dir()
        assert (Path(plaza.source_path) / "SKILL.md").read_text(encoding="utf-8") == "# v2 content\n"
        # 快照独立于个人库目录：update_my_skill 覆盖 local 不影响快照（F-29 磁盘层）
        (local / "SKILL.md").write_text("# overwritten\n", encoding="utf-8")
        assert (Path(plaza.source_path) / "SKILL.md").read_text(encoding="utf-8") == "# v2 content\n"

    async def test_merge_无plaza_id按编码回退查找(self, service, fake_db, admin, audit_mock):
        plaza = PmcpSkillPlaza(id=66, skill_code="fb", skill_name="FB", status="PUBLISHED")
        fake_db.seed(plaza)
        fake_db.plaza_lookup_result = plaza
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", origin="PLAZA", plaza_id=None, skill_code="fb"))
        await service.review(admin, skill.id, "merge", iteration_note="回退合并")
        assert plaza.iteration_note == "回退合并"

    async def test_merge_原创skill被拒(self, service, fake_db, admin, audit_mock):
        fake_db.seed(make_skill(status="PENDING_REVIEW", origin="ORIGINAL"))
        with pytest.raises(SkillReviewError) as ei:
            await service.review(admin, 1, "merge")
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_reject_转已拒绝并存原因(self, service, fake_db, admin, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW"))
        res = await service.review(admin, skill.id, "reject", comment="含内部引用")
        assert skill.status == "REJECTED"
        assert skill.review_comment == "含内部引用"
        assert res.action == "review_reject"
        assert audit_mock.await_args.kwargs["extra_data"]["reason"] == "含内部引用"

    async def test_非admin审核被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="PENDING_REVIEW"))
        with pytest.raises(SkillReviewError) as ei:
            await service.review(owner, 1, "approve")
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_非审核中不可审核(self, service, fake_db, admin, audit_mock):
        fake_db.seed(make_skill(status="DRAFT"))
        with pytest.raises(SkillReviewError) as ei:
            await service.review(admin, 1, "approve")
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非法action被拒(self, service, fake_db, admin, audit_mock):
        fake_db.seed(make_skill(status="PENDING_REVIEW"))
        with pytest.raises(SkillReviewError) as ei:
            await service.review(admin, 1, "bad_action")
        assert ei.value.error_code == CODE_INVALID_STATE


# ==================== 撤回 ====================


class TestWithdraw:
    async def test_撤回审核中转撤回(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW"))
        res = await service.withdraw(owner, skill.id)
        assert skill.status == "WITHDRAWN"
        assert res.action == "withdraw"

    async def test_非审核中撤回被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="DRAFT"))
        with pytest.raises(SkillReviewError) as ei:
            await service.withdraw(owner, 1)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非本人撤回被拒(self, service, fake_db, other_dev, audit_mock):
        fake_db.seed(make_skill(status="PENDING_REVIEW", inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await service.withdraw(other_dev, 1)
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== 分享迭代解决（F-30）====================


class TestResolveShareIteration:
    async def test_迭代转已启用(self, service, fake_db, owner, audit_mock):
        # M4.3：iterate 需广场副本（快照缺失降级为仅元数据同步）
        plaza = PmcpSkillPlaza(id=55, skill_code="demo-skill", skill_name="PL Name", version="0.2.0", status="PUBLISHED")
        fake_db.seed(plaza)
        skill = fake_db.seed(make_skill(status="SHARE_ITERATION", plaza_id=55, origin="PLAZA"))
        res = await service.resolve_share_iteration(owner, skill.id, "iterate")
        assert skill.status == "ENABLED"
        assert res.action == "resolve_iteration_iterate"
        assert audit_mock.await_args.kwargs["extra_data"]["choice"] == "iterate"
        assert skill.skill_name == "PL Name"   # 元数据同步（采纳广场口径）
        assert skill.version == "0.2.0"

    async def test_iterate_广场副本缺失仅同步元数据(self, service, fake_db, owner, audit_mock):
        """无快照（source_path 空）时降级：不拖断状态转移，content_merged=False。"""
        skill = fake_db.seed(make_skill(status="SHARE_ITERATION", plaza_id=55, origin="PLAZA"))
        plaza = PmcpSkillPlaza(id=55, skill_code="demo-skill", skill_name="Meta Only", version="0.3.0", status="PUBLISHED", source_path=None)
        fake_db.seed(plaza)
        res = await service.resolve_share_iteration(owner, skill.id, "iterate")
        assert skill.status == "ENABLED"
        assert skill.skill_name == "Meta Only"
        assert audit_mock.await_args.kwargs["extra_data"]["content_merged"] is False

    async def test_iterate_内容级覆盖并版本存档(self, service, fake_db, owner, audit_mock, tmp_path):
        """M4.3 全链路：广场快照覆盖本地 + 重放审计 + 版本化存档（F-28）。"""
        local = tmp_path / "demo-skill"
        local.mkdir()
        (local / "SKILL.md").write_text("# local old\n", encoding="utf-8")
        snap = tmp_path / "_plaza" / "55"
        snap.mkdir(parents=True)
        (snap / "SKILL.md").write_text("---\nname: PL Name\ndescription: d\nversion: 0.2.0\n---\n# plaza new\n", encoding="utf-8")
        settings_mock = MagicMock()
        settings_mock.skill.upload_dir = str(tmp_path)
        fake_db.seed(PmcpSkillPlaza(id=55, skill_code="demo-skill", skill_name="PL Name", version="0.2.0", status="PUBLISHED", source_path=str(snap), source_checksum="c" * 64))
        skill = fake_db.seed(make_skill(status="SHARE_ITERATION", plaza_id=55, origin="PLAZA", source_path=str(local), version="0.1.0"))
        with patch("platform_mcp.review.service.get_settings", return_value=settings_mock):
            res = await service.resolve_share_iteration(owner, skill.id, "iterate")
        assert res.action == "resolve_iteration_iterate"
        assert skill.status == "ENABLED"
        assert (local / "SKILL.md").read_text(encoding="utf-8").startswith("---")  # 磁盘层覆盖
        assert skill.source_path == str(local)
        assert skill.source_checksum == "c" * 64
        assert skill.audit_status in {"passed", "warning", "failed"}
        assert audit_mock.await_args.kwargs["extra_data"]["content_merged"] is True
        archived = fake_db._added[0]
        assert archived.version == "0.2.0"  # 广场版本入档

    async def test_保留转已启用(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="SHARE_ITERATION"))
        res = await service.resolve_share_iteration(owner, skill.id, "keep")
        assert skill.status == "ENABLED"
        assert res.action == "resolve_iteration_keep"

    async def test_非分享迭代被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="ENABLED"))
        with pytest.raises(SkillReviewError) as ei:
            await service.resolve_share_iteration(owner, 1, "iterate")
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非本人解决迭代被拒(self, service, fake_db, other_dev, audit_mock):
        fake_db.seed(make_skill(status="SHARE_ITERATION", inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await service.resolve_share_iteration(other_dev, 1, "keep")
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== 修改重编辑 / 恢复 ====================


class TestReviseRestore:
    async def test_拒绝后修改回草稿(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="REJECTED", review_comment="原因"))
        res = await service.revise(owner, skill.id)
        assert skill.status == "DRAFT"
        assert res.action == "revise"

    async def test_非法状态修改被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="DRAFT"))
        with pytest.raises(SkillReviewError) as ei:
            await service.revise(owner, 1)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_撤回后恢复回草稿(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="WITHDRAWN"))
        res = await service.restore(owner, skill.id)
        assert skill.status == "DRAFT"
        assert res.action == "restore"

    async def test_非法状态恢复被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="ENABLED"))
        with pytest.raises(SkillReviewError) as ei:
            await service.restore(owner, 1)
        assert ei.value.error_code == CODE_INVALID_STATE


# ==================== 启停（含 F-32 停用视同撤回）====================


class TestSetEnabled:
    async def test_停用已启用转停用(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="ENABLED"))
        res = await service.set_enabled(owner, skill.id, enabled=False)
        assert skill.status == "DISABLED"
        assert res.action == "disable"

    async def test_停用审核中视同撤回(self, service, fake_db, owner, audit_mock):
        # F-32：已提交未过审的 Skill 停用 → WITHDRAWN
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW"))
        res = await service.set_enabled(owner, skill.id, enabled=False)
        assert skill.status == "WITHDRAWN"
        assert res.action == "withdraw_via_disable"

    async def test_启用已停用转启用(self, service, fake_db, owner, audit_mock):
        skill = fake_db.seed(make_skill(status="DISABLED"))
        res = await service.set_enabled(owner, skill.id, enabled=True)
        assert skill.status == "ENABLED"
        assert res.action == "enable"

    async def test_非法启停被拒(self, service, fake_db, owner, audit_mock):
        fake_db.seed(make_skill(status="ENABLED"))
        with pytest.raises(SkillReviewError) as ei:
            await service.set_enabled(owner, 1, enabled=True)  # ENABLED + enable 非法
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非本人启停被拒(self, service, fake_db, other_dev, audit_mock):
        fake_db.seed(make_skill(status="ENABLED", inserted_by="dev01"))
        with pytest.raises(SkillReviewError) as ei:
            await service.set_enabled(other_dev, 1, enabled=False)
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== 可见性矩阵（F-27）====================


class TestVisibility:
    def test_本人可见草稿(self, service, owner):
        assert service.is_visible_to(owner, make_skill(status="DRAFT", inserted_by="dev01")) is True

    def test_admin不可见他人草稿(self, service, admin):
        assert service.is_visible_to(admin, make_skill(status="DRAFT", inserted_by="dev01")) is False

    def test_admin不可见他人已拒绝(self, service, admin):
        assert service.is_visible_to(admin, make_skill(status="REJECTED", inserted_by="dev01")) is False

    def test_admin可见审核中(self, service, admin):
        assert service.is_visible_to(admin, make_skill(status="PENDING_REVIEW", inserted_by="dev01")) is True

    def test_admin可见广场已发布(self, service, admin):
        skill = make_skill(status="ENABLED", share_status="shared", inserted_by="dev01")
        assert service.is_visible_to(admin, skill) is True

    def test_admin不可见未分享已启用(self, service, admin):
        skill = make_skill(status="ENABLED", share_status="unshared", inserted_by="dev01")
        assert service.is_visible_to(admin, skill) is False

    def test_其他dev不可见他人skill(self, service, other_dev):
        skill = make_skill(status="ENABLED", share_status="shared", inserted_by="dev01")
        assert service.is_visible_to(other_dev, skill) is False

    def test_内置skill仅admin可见(self, service, admin, other_dev):
        skill = make_skill(status="ENABLED", register_method="decorator", inserted_by="system")
        assert service.is_visible_to(admin, skill) is True
        assert service.is_visible_to(other_dev, skill) is False

    def test_本人MCP可用态(self, service):
        assert service.owner_can_use_mcp(make_skill(status="DRAFT")) is True
        assert service.owner_can_use_mcp(make_skill(status="PENDING_REVIEW")) is True
        assert service.owner_can_use_mcp(make_skill(status="ENABLED")) is True

    def test_本人MCP不可用态(self, service):
        assert service.owner_can_use_mcp(make_skill(status="REJECTED")) is False
        assert service.owner_can_use_mcp(make_skill(status="WITHDRAWN")) is False
        assert service.owner_can_use_mcp(make_skill(status="DISABLED")) is False


# ==================== 边界 / Actor / 不存在 ====================


class TestEdgeCases:
    async def test_skill不存在(self, service, fake_db, owner, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await service.submit_for_review(owner, 9999)
        assert ei.value.error_code == CODE_NOT_FOUND

    def test_actor_from_user_dict(self):
        user = {"id": 2, "username": "dev01", "role_code": "developer", "locale": "zh-CN"}
        actor = ReviewActor.from_user_dict(user, trace_id="t1")
        assert actor.username == "dev01"
        assert actor.role_code == "developer"
        assert actor.user_id == 2
        assert actor.locale == "zh-CN"
        assert actor.trace_id == "t1"
        assert actor.is_admin is False

    def test_actor_admin判定(self):
        actor = ReviewActor.from_user_dict({"username": "admin", "role_code": "admin", "id": 1})
        assert actor.is_admin is True

    def test_actor_role缺失回退developer(self):
        actor = ReviewActor.from_user_dict({"username": "x"})
        assert actor.role_code == "developer"

    async def test_approve无对应用户时uploader为空(self, service, fake_db, admin, audit_mock):
        skill = fake_db.seed(make_skill(status="PENDING_REVIEW", inserted_by="ghost"))
        fake_db.user_id_result = None
        await service.review(admin, skill.id, "approve")
        plaza = fake_db._store[(PmcpSkillPlaza, skill.plaza_id)]
        assert plaza.uploader_id is None


# ==================== M4.3 快照助手 / 差异查询（F-30 内容级）====================


class TestSnapshotHelpers:
    def test_快照与恢复往返一致(self, tmp_path):
        src = tmp_path / "code"
        (src / "sub").mkdir(parents=True)
        (src / "SKILL.md").write_text("# x\n", encoding="utf-8")
        (src / "sub" / "tool.py").write_text("print(1)\n", encoding="utf-8")
        snap = snapshot_plaza_source(str(src), 42)
        assert snap and "_plaza" in snap.replace("\\", "/")
        assert (Path(snap) / "SKILL.md").read_text(encoding="utf-8") == "# x\n"
        assert (Path(snap) / "sub" / "tool.py").exists()
        # 二次快照覆盖（内容更新）
        (src / "SKILL.md").write_text("# y\n", encoding="utf-8")
        snap2 = snapshot_plaza_source(str(src), 42)
        assert (Path(snap2) / "SKILL.md").read_text(encoding="utf-8") == "# y\n"
        # 恢复到个人库目录
        local = restore_snapshot_to_local(snap2, "code2")
        assert local and local.endswith("code2")
        assert (Path(local) / "SKILL.md").read_text(encoding="utf-8") == "# y\n"

    def test_无源码包返回空串(self):
        assert snapshot_plaza_source(None, 1) == ""
        assert snapshot_plaza_source("/not/exists", 1) == ""
        assert restore_snapshot_to_local(None, "c") == ""


class TestBuildIterationDiff:
    def _seed(self, fake_db, tmp_path, *, status="SHARE_ITERATION", inserted_by="dev01"):
        local = tmp_path / "demo-skill"
        local.mkdir(parents=True, exist_ok=True)
        (local / "SKILL.md").write_text("# 本地\n旧\n", encoding="utf-8")
        snap = tmp_path / "_plaza" / "55"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "SKILL.md").write_text("# 广场\n新\n", encoding="utf-8")
        fake_db.seed(PmcpSkillPlaza(id=55, skill_code="demo-skill", skill_name="Demo", status="PUBLISHED", source_path=str(snap)))
        return fake_db.seed(make_skill(status=status, plaza_id=55, origin="PLAZA", source_path=str(local), inserted_by=inserted_by))

    async def test_owner查询返回差异与描述(self, service, fake_db, owner, tmp_path):
        self._seed(fake_db, tmp_path)
        result = await service.build_iteration_diff(owner, 1)
        assert "本地" in result["unified_diff"]
        assert result["added_lines"] >= 1 and result["removed_lines"] >= 1
        assert 0.0 <= result["similarity"] <= 1.0
        assert result["description_zh"]  # 模板兜底（无本地权重时）
        assert result["description_en"]
        assert result["generated_by"] == "template"
        assert result["performance_hint_zh"] is None  # 模板产物无性能提示（M4.4 仅 model 产物附带）

    async def test_admin可查素材不生成描述(self, service, fake_db, admin, tmp_path):
        self._seed(fake_db, tmp_path)
        result = await service.build_iteration_diff_material(admin, 1)
        assert "description_zh" not in result  # 素材版不生成描述（MCP 口径）
        assert result["skill_code"] == "demo-skill"

    async def test_非owner非admin被拒(self, service, fake_db, other_dev, tmp_path):
        self._seed(fake_db, tmp_path)
        with pytest.raises(SkillReviewError) as ei:
            await service.build_iteration_diff(other_dev, 1)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_非迭代态被拒(self, service, fake_db, owner, tmp_path):
        self._seed(fake_db, tmp_path, status="ENABLED")
        with pytest.raises(SkillReviewError) as ei:
            await service.build_iteration_diff(owner, 1)
        assert ei.value.error_code == CODE_INVALID_STATE
