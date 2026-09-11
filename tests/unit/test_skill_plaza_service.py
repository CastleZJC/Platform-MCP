"""单元测试 — 广场动作服务（V3.0 M3.4，架构 §19.5.3 / §19.5.7，计划 F-29/F-34 / 需求 1.1.4）

覆盖：
- copy_plaza_to_personal：可见性校验（一般用户不可复制涉库项，10004）/ 未发布拒绝（10002）/
  复制体字段（origin=PLAZA、status=ENABLED、register_method=copy、plaza_id 链接）/
  skill_code 冲突 10006 二选一（批次 6.2：未决 data / overwrite 本人同源刷新 / retry 换码 / 非法拒绝）；
- remove_my_skill：本人可移除 / 非本人拒绝（10004）/ 内置装饰器拒绝（10003）/ 不存在（10002）；
- block_skill：plaza_id/skill_id 二选一校验（10003）/ 无 user_id 拒绝（10004）/ 重复屏蔽幂等；
- unblock_skill：二选一校验 / 目标不存在幂等成功；
- disable_plaza_skill：仅 admin（非 admin 10004）/ 不存在（10002）/ 停用成功写审计 / 已停用幂等不重复审计；
- rollback_plaza_version（批次4 回滚开放）：仅 admin / 广场或归档不存在（10002）/ 快照缺失（10003）/
  快照复制回生效目录 + DB 字段切换 / 不新建版本行 / 持有者迭代标记联动（reason=rollback）+
  README 迭代段落刷新 / checksum 空保留原值 / 审计留痕；
- list_blocked_skills：user_id 空短路 / plaza + skill 双类型清单 / 附目标展示信息。

用轻量 FakeSession 替代真实 AsyncSession（按 SQL 文本 + literal_binds 分派），
patch write_audit_log 避免审计独立 session 触库。
"""

from __future__ import annotations

import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    CODE_SKILL_CODE_CONFLICT,
    ReviewActor,
    SkillReviewError,
)
from platform_mcp.skills import plaza_service
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillBlacklist, PmcpSkillPlaza


def _sql(stmt) -> str:
    """编译 SQL（尽量内联绑定参数，便于按 skill_code 字面值分派存在性）。"""
    try:
        return str(
            stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
    except Exception:  # pragma: no cover - 兜底
        return str(stmt)


class FakeSession:
    """轻量伪 AsyncSession：仅实现 plaza_service 用到的 get/add/delete/flush/execute。

    未定义 ``commit``——服务若误调用即抛 AttributeError，佐证"mutate+flush 不 commit"。
    """

    def __init__(self) -> None:
        self._store: dict[tuple[type, int], object] = {}
        self._added: list[object] = []
        self.deleted: list[object] = []
        self._id_seq = 9000
        self.flush_count = 0
        # 分派配置
        self.skills_by_code: dict[str, PmcpSkill] = {}  # 编码占用行（copy 冲突分支按 SQL 字面值命中）
        self.blacklist_lookup: PmcpSkillBlacklist | None = None  # block/unblock 幂等探测
        self.blacklist_entries: list[PmcpSkillBlacklist] = []    # list_blocked 清单
        self.plaza_rows: list[PmcpSkillPlaza] = []               # list_blocked plaza_map
        self.skill_rows: list[PmcpSkill] = []                     # list_blocked skill_map
        self.version_row_lookup: PmcpPlazaVersion | None = None   # rollback 版本归档探测

    def seed(self, obj):
        self._store[(type(obj), obj.id)] = obj
        if isinstance(obj, PmcpSkill):
            self.skills_by_code[obj.skill_code] = obj
        return obj

    async def get(self, model, pk):
        return self._store.get((model, pk))

    def add(self, obj) -> None:
        self._added.append(obj)

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        for obj in self._added:
            if getattr(obj, "id", None) is None:
                obj.id = self._id_seq
                self._id_seq += 1
                self._store[(type(obj), obj.id)] = obj

    async def execute(self, stmt, params=None):
        sql = _sql(stmt)
        upper = sql.upper()
        result = MagicMock()
        if "pmcp_skill_blacklist" in sql:
            if "ORDER BY" in upper:
                result.scalars.return_value.all.return_value = list(self.blacklist_entries)
            else:
                result.scalar_one_or_none.return_value = self.blacklist_lookup
        elif "pmcp_plaza_version" in sql:
            # rollback_plaza_version：归档版本行探测
            result.scalar_one_or_none.return_value = self.version_row_lookup
        elif "pmcp_skill_plaza" in sql:
            result.scalars.return_value.all.return_value = list(self.plaza_rows)
        elif "WHERE PMCP_SKILL.SKILL_CODE" in upper:
            # copy_plaza_to_personal 编码占用探测（基编码 / retry 新编码）：返回真实 PmcpSkill 行或 None
            hit = next((c for c in self.skills_by_code if f"'{c}'" in sql), None)
            result.scalar_one_or_none.return_value = self.skills_by_code[hit] if hit else None
        elif "pmcp_skill" in sql:
            result.scalars.return_value.all.return_value = list(self.skill_rows)
        else:
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
        return result


def _plaza(pid=5, code="oracle-backup", name="Oracle 备份", desc="数据库备份", flags=None,
           status="PUBLISHED") -> PmcpSkillPlaza:
    return PmcpSkillPlaza(
        id=pid, skill_code=code, skill_name=name, description=desc, involve_flags=flags,
        status=status, version="1.0", source_path="/store/plaza", source_checksum="p-check",
    )


def _skill(sid=1, code="demo", owner="dev01", reg="upload", **kw) -> PmcpSkill:
    defaults = dict(
        id=sid, skill_code=code, skill_name=code, description="d", status="ENABLED",
        register_method=reg, tool_count=0, inserted_by=owner, origin="ORIGINAL",
        share_status="unshared", plaza_id=None,
    )
    defaults.update(kw)
    return PmcpSkill(**defaults)


@pytest.fixture
def db() -> FakeSession:
    return FakeSession()


@pytest.fixture
def dev() -> ReviewActor:
    return ReviewActor(username="dev01", role_code="developer", user_id=2)


@pytest.fixture
def user() -> ReviewActor:
    return ReviewActor(username="user01", role_code="user", user_id=3)


@pytest.fixture
def admin() -> ReviewActor:
    return ReviewActor(username="admin", role_code="admin", user_id=1)


@pytest.fixture
def audit_mock():
    with patch.object(plaza_service, "write_audit_log", new=AsyncMock()) as m:
        yield m


# ==================== copy_plaza_to_personal（add_skill_to_my）====================


class TestCopyPlazaToPersonal:
    async def test_复制成功字段正确(self, db, dev, audit_mock):
        plaza = db.seed(_plaza(pid=5))
        skill = await plaza_service.copy_plaza_to_personal(db, 5, dev)
        assert skill.origin == "PLAZA"
        assert skill.status == "ENABLED"
        assert skill.register_method == "copy"
        assert skill.plaza_id == 5
        assert skill.share_status == "shared"
        assert skill.skill_code == plaza.skill_code  # 基编码空闲 → 原样
        assert skill.inserted_by == "dev01"
        assert skill.source_path == plaza.source_path
        assert skill.version == plaza.version
        assert skill.copied_from_plaza_version == plaza.version  # add-to-my 记来源广场版本（3-way base，设计⑤）

    async def test_复制写审计(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5))
        await plaza_service.copy_plaza_to_personal(db, 5, dev)
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs["resource_type"] == "skill"
        assert kwargs["extra_data"]["action"] == "copy_from_plaza"
        assert kwargs["extra_data"]["plaza_id"] == 5

    async def test_不存在返回10002(self, db, dev, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 999, dev)
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_未发布返回10002(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, status="DISABLED"))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 5, dev)
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_一般用户不可复制涉库项(self, db, user, audit_mock):
        """需求 1.1.4：涉库广场 Skill 对一般用户不可见，复制被拒（10004）"""
        db.seed(_plaza(pid=5, flags=["database"]))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 5, user)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_一般用户不可复制涉服务器项(self, db, user, audit_mock):
        db.seed(_plaza(pid=5, flags=["server"]))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 5, user)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_一般用户可复制无标记项(self, db, user, audit_mock):
        db.seed(_plaza(pid=5, flags=[]))
        skill = await plaza_service.copy_plaza_to_personal(db, 5, user)
        assert skill.origin == "PLAZA"

    async def test_admin可复制涉库项(self, db, admin, audit_mock):
        db.seed(_plaza(pid=5, flags=["database"]))
        skill = await plaza_service.copy_plaza_to_personal(db, 5, admin)
        assert skill.plaza_id == 5

    # ---- 批次 6.2：skill_code 冲突 10006 二选一（派生码 {code}-{username} 退役）----

    def _own_copy(self, db, code="oracle-backup", plaza_id=5) -> PmcpSkill:
        """本人同广场 PLAZA 副本占用基编码（overwrite_available=True 的唯一形态）。"""
        return db.seed(_skill(sid=1, code=code, owner="dev01", reg="copy", origin="PLAZA",
                              plaza_id=plaza_id, skill_name="旧名", description="旧描述",
                              version="0.1", status="DISABLED", share_status="unshared"))

    async def test_编码冲突未决返回10006结构化数据_本人同源可覆盖(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        occupied = self._own_copy(db)
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 5, dev)
        assert ei.value.error_code == CODE_SKILL_CODE_CONFLICT
        assert ei.value.data == {
            "conflict_skill_id": occupied.id,
            "conflict_code": "oracle-backup",
            "overwrite_available": True,
        }
        audit_mock.assert_not_awaited()

    async def test_编码冲突他人占用不可覆盖(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev02", reg="copy",
                       origin="PLAZA", plaza_id=5))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 5, dev)
        assert ei.value.error_code == CODE_SKILL_CODE_CONFLICT
        assert ei.value.data["overwrite_available"] is False

    async def test_编码冲突本人原创占用不可覆盖(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev01", reg="upload",
                       origin="ORIGINAL"))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(db, 5, dev)
        assert ei.value.error_code == CODE_SKILL_CODE_CONFLICT
        assert ei.value.data["overwrite_available"] is False

    async def test_覆盖本人同源副本刷新字段不新建行(self, db, dev, audit_mock):
        plaza = db.seed(_plaza(pid=5, code="oracle-backup", name="Oracle 备份 v2"))
        occupied = self._own_copy(db)
        skill = await plaza_service.copy_plaza_to_personal(
            db, 5, dev, conflict_resolution="overwrite")
        assert skill is occupied  # 覆盖保留行，不新建
        assert occupied.skill_name == plaza.skill_name
        assert occupied.description == plaza.description
        assert occupied.version == plaza.version
        assert occupied.source_path == plaza.source_path
        assert occupied.source_checksum == plaza.source_checksum
        assert occupied.copied_from_plaza_version == plaza.version
        assert occupied.status == "ENABLED"  # 置回启用（曾 DISABLED）
        assert occupied.share_status == "shared"
        assert occupied.updated_by == "dev01"
        assert db._added == []  # 无新行
        assert db.flush_count >= 1
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs["extra_data"]["action"] == "copy_from_plaza_overwrite"
        assert kwargs["extra_data"]["plaza_id"] == 5

    async def test_覆盖他人副本被拒10003(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev02", reg="copy",
                       origin="PLAZA", plaza_id=5))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(
                db, 5, dev, conflict_resolution="overwrite")
        assert ei.value.error_code == CODE_INVALID_STATE
        audit_mock.assert_not_awaited()

    async def test_覆盖本人原创占用被拒10003(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev01", reg="upload",
                       origin="ORIGINAL"))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(
                db, 5, dev, conflict_resolution="overwrite")
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_换码重试成功以新编码复制(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev02"))  # 基编码他人占用
        skill = await plaza_service.copy_plaza_to_personal(
            db, 5, dev, conflict_resolution="retry", new_code="my-oracle-backup")
        assert skill.skill_code == "my-oracle-backup"
        assert skill.origin == "PLAZA"
        assert skill.inserted_by == "dev01"
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.kwargs["extra_data"]["action"] == "copy_from_plaza"

    async def test_换码重试新编码仍冲突再抛10006(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev02"))
        mine = db.seed(_skill(sid=2, code="my-tool-v2", owner="dev01", reg="copy",
                              origin="PLAZA", plaza_id=5))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(
                db, 5, dev, conflict_resolution="retry", new_code="my-tool-v2")
        assert ei.value.error_code == CODE_SKILL_CODE_CONFLICT
        assert ei.value.data == {
            "conflict_skill_id": mine.id,
            "conflict_code": "my-tool-v2",
            "overwrite_available": True,  # 新编码占用恰为本人同源副本 → 可改走 overwrite
        }

    async def test_换码重试缺new_code被拒10003(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev02"))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(
                db, 5, dev, conflict_resolution="retry", new_code="  ")
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_非法resolution被拒10003(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5, code="oracle-backup"))
        db.seed(_skill(sid=1, code="oracle-backup", owner="dev01", reg="copy",
                       origin="PLAZA", plaza_id=5))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.copy_plaza_to_personal(
                db, 5, dev, conflict_resolution="force")
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_复制flush不commit(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5))
        await plaza_service.copy_plaza_to_personal(db, 5, dev)
        assert db.flush_count >= 1


# ==================== remove_my_skill ====================


class TestRemoveMySkill:
    async def test_本人移除成功(self, db, dev, audit_mock):
        skill = db.seed(_skill(sid=1, owner="dev01", reg="upload"))
        await plaza_service.remove_my_skill(db, 1, dev)
        assert skill in db.deleted
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.kwargs["extra_data"]["action"] == "remove_my_skill"

    async def test_移除广场复制体允许(self, db, dev, audit_mock):
        db.seed(_skill(sid=1, owner="dev01", reg="copy", origin="PLAZA"))
        await plaza_service.remove_my_skill(db, 1, dev)
        assert len(db.deleted) == 1

    async def test_不存在返回10002(self, db, dev, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.remove_my_skill(db, 999, dev)
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_非本人移除被拒(self, db, dev, audit_mock):
        db.seed(_skill(sid=1, owner="dev02"))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.remove_my_skill(db, 1, dev)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_admin可移除他人(self, db, admin, audit_mock):
        skill = db.seed(_skill(sid=1, owner="dev02"))
        await plaza_service.remove_my_skill(db, 1, admin)
        assert skill in db.deleted

    async def test_内置装饰器不可移除(self, db, dev, audit_mock):
        db.seed(_skill(sid=1, owner="dev01", reg="decorator"))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.remove_my_skill(db, 1, dev)
        assert ei.value.error_code == CODE_INVALID_STATE


# ==================== block_skill ====================


class TestBlockSkill:
    async def test_屏蔽广场项成功(self, db, dev, audit_mock):
        entry = await plaza_service.block_skill(db, dev, plaza_id=5, reason="不需要")
        assert isinstance(entry, PmcpSkillBlacklist)
        assert entry.user_id == 2
        assert entry.target_plaza_id == 5
        assert entry.target_skill_id is None
        assert entry.reason == "不需要"
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.kwargs["extra_data"]["action"] == "block_skill"

    async def test_屏蔽个人项成功(self, db, dev, audit_mock):
        entry = await plaza_service.block_skill(db, dev, skill_id=7)
        assert entry.target_skill_id == 7
        assert entry.target_plaza_id is None

    async def test_二选一同时给出被拒(self, db, dev, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.block_skill(db, dev, plaza_id=5, skill_id=7)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_二选一同时为空被拒(self, db, dev, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.block_skill(db, dev)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_无user_id被拒(self, db, audit_mock):
        actor = ReviewActor(username="ghost", role_code="developer", user_id=None)
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.block_skill(db, actor, plaza_id=5)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_重复屏蔽幂等返回既有(self, db, dev, audit_mock):
        existing = PmcpSkillBlacklist(id=88, user_id=2, target_plaza_id=5)
        db.blacklist_lookup = existing
        entry = await plaza_service.block_skill(db, dev, plaza_id=5)
        assert entry is existing
        audit_mock.assert_not_awaited()  # 幂等不重复审计
        assert db.deleted == []


# ==================== unblock_skill ====================


class TestUnblockSkill:
    async def test_撤销屏蔽成功(self, db, dev, audit_mock):
        existing = PmcpSkillBlacklist(id=88, user_id=2, target_plaza_id=5)
        db.blacklist_lookup = existing
        await plaza_service.unblock_skill(db, dev, plaza_id=5)
        assert existing in db.deleted
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.kwargs["extra_data"]["action"] == "unblock_skill"

    async def test_目标不存在幂等成功(self, db, dev, audit_mock):
        db.blacklist_lookup = None
        await plaza_service.unblock_skill(db, dev, plaza_id=5)  # 不抛异常
        assert db.deleted == []
        audit_mock.assert_not_awaited()

    async def test_二选一校验(self, db, dev, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.unblock_skill(db, dev)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_无user_id被拒(self, db, audit_mock):
        actor = ReviewActor(username="ghost", role_code="developer", user_id=None)
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.unblock_skill(db, actor, plaza_id=5)
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== disable_plaza_skill ====================


class TestDisablePlazaSkill:
    async def test_admin停用成功写审计(self, db, admin, audit_mock):
        plaza = db.seed(_plaza(pid=5))
        result = await plaza_service.disable_plaza_skill(db, 5, admin)
        assert result.status == "DISABLED"
        assert db.flush_count >= 1
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs["resource_type"] == "skill"
        assert kwargs["extra_data"]["action"] == "disable_plaza_skill"
        assert kwargs["extra_data"]["plaza_id"] == 5

    async def test_非admin被拒(self, db, dev, audit_mock):
        db.seed(_plaza(pid=5))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.disable_plaza_skill(db, 5, dev)
        assert ei.value.error_code == CODE_FORBIDDEN
        audit_mock.assert_not_awaited()

    async def test_一般用户同样被拒(self, db, user, audit_mock):
        db.seed(_plaza(pid=5))
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.disable_plaza_skill(db, 5, user)
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_不存在返回10002(self, db, admin, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.disable_plaza_skill(db, 999, admin)
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_已停用幂等不重复审计(self, db, admin, audit_mock):
        plaza = db.seed(_plaza(pid=5, status="DISABLED"))
        result = await plaza_service.disable_plaza_skill(db, 5, admin)
        assert result is plaza
        audit_mock.assert_not_awaited()


# ==================== list_blocked_skills ====================


class TestListBlockedSkills:
    async def test_无user_id短路返回空(self, db):
        assert await plaza_service.list_blocked_skills(db, None) == []

    async def test_空黑名单返回空(self, db):
        db.blacklist_entries = []
        assert await plaza_service.list_blocked_skills(db, 2) == []

    async def test_广场类型清单附展示信息(self, db):
        db.blacklist_entries = [PmcpSkillBlacklist(id=1, user_id=2, target_plaza_id=5, reason="x")]
        db.plaza_rows = [_plaza(pid=5, code="oracle-backup", name="Oracle 备份")]
        items = await plaza_service.list_blocked_skills(db, 2)
        assert len(items) == 1
        assert items[0]["target_type"] == "plaza"
        assert items[0]["target_id"] == 5
        assert items[0]["skill_code"] == "oracle-backup"
        assert items[0]["skill_name"] == "Oracle 备份"
        assert items[0]["reason"] == "x"

    async def test_个人类型清单附展示信息(self, db):
        db.blacklist_entries = [PmcpSkillBlacklist(id=2, user_id=2, target_skill_id=7)]
        db.skill_rows = [_skill(sid=7, code="demo-skill")]
        items = await plaza_service.list_blocked_skills(db, 2)
        assert len(items) == 1
        assert items[0]["target_type"] == "skill"
        assert items[0]["target_id"] == 7
        assert items[0]["skill_code"] == "demo-skill"

    async def test_目标已删除时展示信息为空(self, db):
        db.blacklist_entries = [PmcpSkillBlacklist(id=3, user_id=2, target_plaza_id=99)]
        db.plaza_rows = []  # 广场副本已不存在
        items = await plaza_service.list_blocked_skills(db, 2)
        assert items[0]["skill_code"] is None
        assert items[0]["target_id"] == 99

    async def test_混合双类型清单(self, db):
        db.blacklist_entries = [
            PmcpSkillBlacklist(id=1, user_id=2, target_plaza_id=5),
            PmcpSkillBlacklist(id=2, user_id=2, target_skill_id=7),
        ]
        db.plaza_rows = [_plaza(pid=5)]
        db.skill_rows = [_skill(sid=7)]
        items = await plaza_service.list_blocked_skills(db, 2)
        types = {it["target_type"] for it in items}
        assert types == {"plaza", "skill"}


# ==================== rollback_plaza_version（批次4 回滚开放）====================


class TestRollbackPlazaVersion:
    """回滚 = 版本变更：快照复制回 _plaza/{pid}、字段切换、迭代标记联动（无邮件）、不新建版本行。"""

    def _make_version_row(self, tmp_path, version="0.9.0", checksum="snap-check") -> PmcpPlazaVersion:
        snap = tmp_path / "_plaza_versions" / "5" / version
        snap.mkdir(parents=True)
        (snap / "SKILL.md").write_text("# archived", encoding="utf-8")
        (snap / "refs.md").write_text("refs", encoding="utf-8")
        return PmcpPlazaVersion(
            id=11, plaza_id=5, version=version, snapshot_path=str(snap),
            checksum=checksum, file_manifest=[{"path": "SKILL.md"}, {"path": "refs.md"}],
        )

    def _patch_fs(self, tmp_path):
        # _plaza_snapshot_dir 经 review.service.get_settings 解析 upload_dir
        settings = MagicMock()
        settings.skill.upload_dir = str(tmp_path)
        return patch("platform_mcp.review.service.get_settings", return_value=settings)

    async def test_admin回滚成功_快照复制与字段切换(self, db, admin, audit_mock, tmp_path):
        plaza = db.seed(_plaza(pid=5))
        row = self._make_version_row(tmp_path)
        db.version_row_lookup = row
        mark_mock = AsyncMock(return_value=2)
        readme_mock = AsyncMock(return_value=True)
        with self._patch_fs(tmp_path), \
             patch.object(plaza_service, "mark_plaza_holders_for_iteration", mark_mock), \
             patch.object(plaza_service, "refresh_plaza_readme_iteration", readme_mock):
            result = await plaza_service.rollback_plaza_version(db, 5, "0.9.0", admin)
        # 快照复制回生效目录 _plaza/5/
        live = tmp_path / "_plaza" / "5"
        assert (live / "SKILL.md").read_text(encoding="utf-8") == "# archived"
        assert (live / "refs.md").exists()
        # DB 字段切换（版本/路径/校验和/操作人）
        assert plaza.version == "0.9.0"
        assert plaza.source_path == str(live)
        assert plaza.source_checksum == "snap-check"
        assert plaza.updated_by == "admin"
        # 返回结构
        assert result == {
            "plaza_id": 5, "skill_code": plaza.skill_code, "from_version": "1.0",
            "to_version": "0.9.0", "file_count": 2, "holders_marked": 2,
        }
        assert db.flush_count >= 1
        assert db._added == []  # 不新建版本行（回滚内容=归档版）

    async def test_回滚联动迭代标记与README刷新(self, db, admin, audit_mock, tmp_path):
        db.seed(_plaza(pid=5))
        db.version_row_lookup = self._make_version_row(tmp_path)
        mark_mock = AsyncMock(return_value=1)
        readme_mock = AsyncMock(return_value=True)
        with self._patch_fs(tmp_path), \
             patch.object(plaza_service, "mark_plaza_holders_for_iteration", mark_mock), \
             patch.object(plaza_service, "refresh_plaza_readme_iteration", readme_mock):
            await plaza_service.rollback_plaza_version(db, 5, "0.9.0", admin)
        mark_mock.assert_awaited_once()
        assert mark_mock.await_args.kwargs["reason"] == "rollback"
        assert mark_mock.await_args.kwargs["new_version"] == "0.9.0"
        readme_mock.assert_awaited_once()
        audit_mock.assert_awaited_once()
        extra = audit_mock.await_args.kwargs["extra_data"]
        assert extra["action"] == "rollback_plaza_version"
        assert extra["from_version"] == "1.0"
        assert extra["to_version"] == "0.9.0"
        assert extra["holders_marked"] == 1

    async def test_非admin被拒(self, db, dev, audit_mock, tmp_path):
        db.seed(_plaza(pid=5))
        db.version_row_lookup = self._make_version_row(tmp_path)
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.rollback_plaza_version(db, 5, "0.9.0", dev)
        assert ei.value.error_code == CODE_FORBIDDEN
        audit_mock.assert_not_awaited()

    async def test_广场不存在10002(self, db, admin, audit_mock):
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.rollback_plaza_version(db, 999, "0.9.0", admin)
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_版本归档不存在10002(self, db, admin, audit_mock):
        db.seed(_plaza(pid=5))
        db.version_row_lookup = None
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.rollback_plaza_version(db, 5, "9.9.9", admin)
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_快照目录缺失10003(self, db, admin, audit_mock, tmp_path):
        db.seed(_plaza(pid=5))
        row = self._make_version_row(tmp_path)
        shutil.rmtree(row.snapshot_path)  # 归档在、目录丢失
        db.version_row_lookup = row
        with pytest.raises(SkillReviewError) as ei:
            await plaza_service.rollback_plaza_version(db, 5, "0.9.0", admin)
        assert ei.value.error_code == CODE_INVALID_STATE

    async def test_归档checksum为空保留原校验和(self, db, admin, audit_mock, tmp_path):
        plaza = db.seed(_plaza(pid=5))
        db.version_row_lookup = self._make_version_row(tmp_path, checksum=None)
        mark_mock = AsyncMock(return_value=0)
        with self._patch_fs(tmp_path), \
             patch.object(plaza_service, "mark_plaza_holders_for_iteration", mark_mock), \
             patch.object(plaza_service, "refresh_plaza_readme_iteration", AsyncMock()):
            await plaza_service.rollback_plaza_version(db, 5, "0.9.0", admin)
        assert plaza.source_checksum == "p-check"  # 原值不被清空
