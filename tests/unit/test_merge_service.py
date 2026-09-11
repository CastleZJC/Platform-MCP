"""单元测试 — 广场 merge 工作台服务（设计定稿④，2026-09-10，批次3）

覆盖五场景 + 全链路：
- ①原创 B 并入广场 A（build 来源不限 origin；publish 后 A 的 code/name 不变、description 取主源）；
- ②最新版迭代（基线=广场当前快照）；
- ③老版本 3-way（基线=源 ``copied_from_plaza_version`` 的历史快照）；
- ④双用户主次源（同路径冲突清单 + 逐文件裁决：主源默认 / 次源改判 / base 回退 / 非法裁决拒绝）；
- ⑤admin 自持副本（发布后与其他持有者同样被置迭代态）。

发布全链路：🔴 终审阻断（critical_count>0 → 10003 + 审计 failed）/ 快照覆盖 ``_plaza/{pid}`` /
版本归档（source_version=主源提交人版本）/ 广场字段刷新 / 持有者标记 reason=merge_publish /
skill_review 组通知 / 临时包清理与 token 终结（discard / 二次 publish 拒绝）。

用轻量 FakeSession 按 SQL 表名分派（同 test_review_service 口径），磁盘链路走 tmp_path
（get_settings 双命名空间 patch：merge_service + review.service）。
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
)
from platform_mcp.skills.merge_service import (
    build_merge_version,
    list_plaza_versions,
    publish_merge_version,
    serialize_merge,
)
from platform_mcp.skills.models import PmcpPlazaMerge, PmcpPlazaVersion, PmcpSkillPlaza


class FakeSession:
    """merge 服务用伪 AsyncSession：get/add/flush + 按 SQL 表名分派 execute。"""

    def __init__(self) -> None:
        self._store: dict[tuple[type, int], object] = {}
        self._added: list[object] = []
        self._id_seq = 7000
        self.flush_count = 0
        self.plaza_lookup_result: PmcpSkillPlaza | None = None
        self.merge_row_result: PmcpPlazaMerge | None = None
        self.blacklist_holders: list[str] = []
        self.iteration_holders: list[PmcpSkill] = []
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
        if "pmcp_skill_blacklist" in sql:
            result.scalars.return_value.all.return_value = list(self.blacklist_holders)
        elif "pmcp_skill.status IN" in sql:
            result.scalars.return_value.all.return_value = list(self.iteration_holders)
        elif "pmcp_plaza_merge" in sql:
            # 显式注入优先；否则回退 store 中最近 build 的行（token WHERE 由真实 SQL 保证，此处模拟取回）
            if self.merge_row_result is not None:
                result.scalar_one_or_none.return_value = self.merge_row_result
            else:
                merges = [o for (t, _pk), o in self._store.items() if t is PmcpPlazaMerge]
                result.scalar_one_or_none.return_value = merges[-1] if merges else None
        elif "pmcp_skill_plaza" in sql:
            result.scalar_one_or_none.return_value = self.plaza_lookup_result
        else:
            result.scalar_one_or_none.return_value = None
        return result


def make_skill(**kw) -> PmcpSkill:
    defaults: dict = dict(
        id=101,
        skill_code="demo-skill",
        skill_name="Demo",
        description="demo description",
        status="PENDING_REVIEW",
        register_method="upload",
        tool_count=0,
        version="0.1.0",
        source_path="",
        source_checksum="a" * 64,
        inserted_by="dev01",
        origin="ORIGINAL",
        share_status="unshared",
        plaza_id=None,
        review_comment=None,
        copied_from_plaza_version=None,
    )
    defaults.update(kw)
    return PmcpSkill(**defaults)


def make_plaza(**kw) -> PmcpSkillPlaza:
    defaults: dict = dict(
        id=5,
        skill_code="tool-a",
        skill_name="Tool A",
        description="plaza a description",
        status="PUBLISHED",
        version="1.0.0",
        involve_flags=None,
        source_path="",
        source_checksum=None,
    )
    defaults.update(kw)
    return PmcpSkillPlaza(**defaults)


def _write_pkg(base: Path, files: dict[str, str]) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return base


@pytest.fixture
def fake_db() -> FakeSession:
    return FakeSession()


@pytest.fixture
def admin() -> ReviewActor:
    return ReviewActor(username="admin", role_code="admin", user_id=1)


@pytest.fixture
def non_admin() -> ReviewActor:
    return ReviewActor(username="dev01", role_code="developer", user_id=2)


@contextmanager
def _merge_env(tmp_path: Path):
    """统一 patch：settings 双命名空间（upload_dir=tmp_path）+ 审计/向量/README/通知。"""
    settings_mock = MagicMock()
    settings_mock.skill.upload_dir = str(tmp_path)
    audit_mock = AsyncMock()
    index_mock = AsyncMock()
    readme_mock = AsyncMock()
    notify_mock = AsyncMock()
    with (
        patch("platform_mcp.skills.merge_service.get_settings", return_value=settings_mock),
        patch("platform_mcp.review.service.get_settings", return_value=settings_mock),
        patch("platform_mcp.skills.merge_service.write_audit_log", audit_mock),
        patch("platform_mcp.review.service.write_audit_log", audit_mock),
        patch("platform_mcp.skills.merge_service.index_plaza_embedding", index_mock),
        patch("platform_mcp.skills.merge_service.refresh_plaza_readme_iteration", readme_mock),
        patch("platform_mcp.notify.service.dispatch_notification", notify_mock),
    ):
        yield {
            "audit": audit_mock,
            "index": index_mock,
            "readme": readme_mock,
            "notify": notify_mock,
        }


# ==================== build：文件级并集 + 基线解析 + 冲突清单 ====================


class TestBuildMerge:
    async def test_场景1_原创Skill可作源并入广场A(self, fake_db, admin, tmp_path):
        """原创 B（origin=ORIGINAL、无 plaza 关联）可与广场 A 当前快照做并集。"""
        plaza_dir = _write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# A base\n"})
        plaza = fake_db.seed(make_plaza(source_path=str(plaza_dir)))
        b_dir = _write_pkg(tmp_path / "helper-b", {"SKILL.md": "# B content\n", "refs/x.md": "x"})
        b = fake_db.seed(make_skill(id=201, skill_code="helper-b", origin="ORIGINAL", source_path=str(b_dir)))
        with _merge_env(tmp_path):
            result = await build_merge_version(
                fake_db, plaza_id=plaza.id, source_skill_ids=[b.id], actor=admin
            )
        assert result["status"] == "BUILT"
        assert result["base_version"] == "1.0.0（当前）"
        assert result["conflicts"] == []
        row = fake_db._added[0]
        assert isinstance(row, PmcpPlazaMerge) and row.status == "BUILT"
        assert Path(row.snapshot_path).is_dir()
        # 并集：base 保留 + 源文件叠加
        merged_root = Path(row.snapshot_path)
        assert (merged_root / "SKILL.md").read_text(encoding="utf-8") == "# B content\n"
        assert (merged_root / "refs" / "x.md").exists()

    async def test_场景2_基线为广场当前快照(self, fake_db, admin, tmp_path):
        """无 copied_from 的单源（含 origin=PLAZA 最新副本）：基线=当前快照标签。"""
        plaza_dir = _write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# A base\n"})
        plaza = fake_db.seed(make_plaza(version="2.3.4", source_path=str(plaza_dir)))
        s = fake_db.seed(make_skill(
            id=206, origin="PLAZA", plaza_id=5, source_path=str(_write_pkg(tmp_path / "copy", {"SKILL.md": "# v\n"})),
        ))
        with _merge_env(tmp_path):
            result = await build_merge_version(fake_db, plaza_id=5, source_skill_ids=[s.id], actor=admin)
        assert result["base_version"] == "2.3.4（当前）"
        assert result["new_version"] == "2.3.5"  # +patch 预演

    async def test_场景3_单源老版本以copied_from为基线(self, fake_db, admin, tmp_path):
        ver_dir = _write_pkg(tmp_path / "_plaza_versions" / "5" / "0.9.0", {"SKILL.md": "# old base\n"})
        assert ver_dir.is_dir()
        plaza = fake_db.seed(make_plaza(source_path=""))
        s = fake_db.seed(make_skill(
            id=202, origin="PLAZA", plaza_id=5, copied_from_plaza_version="0.9.0",
            source_path=str(_write_pkg(tmp_path / "copy", {"SKILL.md": "# holder edit\n"})),
        ))
        with _merge_env(tmp_path):
            result = await build_merge_version(fake_db, plaza_id=5, source_skill_ids=[s.id], actor=admin)
        assert result["base_version"] == "0.9.0"
        merged_root = Path(fake_db._added[0].snapshot_path)
        assert (merged_root / "SKILL.md").read_text(encoding="utf-8") == "# holder edit\n"

    async def test_显式base_version优先且缺失被拒(self, fake_db, admin, tmp_path):
        plaza = fake_db.seed(make_plaza())
        s = fake_db.seed(make_skill(id=203, copied_from_plaza_version="0.9.0", source_path=""))
        with _merge_env(tmp_path):
            with pytest.raises(Exception) as ei:
                await build_merge_version(
                    fake_db, plaza_id=5, source_skill_ids=[s.id], actor=admin, base_version="8.8.8"
                )
        assert getattr(ei.value, "error_code", None) == CODE_INVALID_STATE

    async def test_场景4_双源同路径冲突默认主源并列候选(self, fake_db, admin, tmp_path):
        plaza_dir = _write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# base v\n", "keep.md": "keep"})
        plaza = fake_db.seed(make_plaza(source_path=str(plaza_dir)))
        d1 = _write_pkg(tmp_path / "u1", {"SKILL.md": "# user1 edit\n"})
        d2 = _write_pkg(tmp_path / "u2", {"SKILL.md": "# user2 edit\n"})
        s1 = fake_db.seed(make_skill(id=211, skill_code="u1", inserted_by="dev01", source_path=str(d1)))
        s2 = fake_db.seed(make_skill(id=212, skill_code="u2", inserted_by="dev02", source_path=str(d2)))
        with _merge_env(tmp_path):
            result = await build_merge_version(
                fake_db, plaza_id=plaza.id, source_skill_ids=[s1.id, s2.id], actor=admin
            )
        assert len(result["conflicts"]) == 1
        conflict = result["conflicts"][0]
        assert conflict["path"] == "SKILL.md"
        assert conflict["default_source_skill_id"] == s1.id  # 主源 = 源列表首位
        roles = [c["role"] for c in conflict["candidates"]]
        assert roles == ["primary", "secondary", "base"]  # base 也在候选（admin 可回退基线）
        merged_root = Path(fake_db._added[0].snapshot_path)
        assert (merged_root / "SKILL.md").read_text(encoding="utf-8") == "# user1 edit\n"
        assert (merged_root / "keep.md").read_text(encoding="utf-8") == "keep"  # base 独有文件保留

    async def test_源目录缺失按空树不阻断(self, fake_db, admin, tmp_path):
        plaza = fake_db.seed(make_plaza(source_path=""))
        s = fake_db.seed(make_skill(id=221, source_path=str(tmp_path / "not-exists")))
        with _merge_env(tmp_path):
            result = await build_merge_version(fake_db, plaza_id=5, source_skill_ids=[s.id], actor=admin)
        assert result["status"] == "BUILT"

    async def test_装饰器源被拒(self, fake_db, admin, tmp_path):
        fake_db.seed(make_plaza())
        s = fake_db.seed(make_skill(id=231, register_method="decorator"))
        with _merge_env(tmp_path):
            with pytest.raises(Exception) as ei:
                await build_merge_version(fake_db, plaza_id=5, source_skill_ids=[s.id], actor=admin)
        assert getattr(ei.value, "error_code", None) == CODE_INVALID_STATE

    async def test_非admin与空源与广场缺失被拒(self, fake_db, admin, non_admin, tmp_path):
        plaza = fake_db.seed(make_plaza())
        s = fake_db.seed(make_skill(id=241))
        with _merge_env(tmp_path):
            with pytest.raises(Exception) as ei:
                await build_merge_version(fake_db, plaza_id=plaza.id, source_skill_ids=[s.id], actor=non_admin)
            assert getattr(ei.value, "error_code", None) == CODE_FORBIDDEN
            with pytest.raises(Exception) as ei2:
                await build_merge_version(fake_db, plaza_id=plaza.id, source_skill_ids=[], actor=admin)
            assert getattr(ei2.value, "error_code", None) == CODE_INVALID_STATE
            with pytest.raises(Exception) as ei3:
                await build_merge_version(fake_db, plaza_id=999, source_skill_ids=[s.id], actor=admin)
            assert getattr(ei3.value, "error_code", None) == CODE_NOT_FOUND

    async def test_源去重保序(self, fake_db, admin, tmp_path):
        plaza = fake_db.seed(make_plaza())
        s = fake_db.seed(make_skill(id=251, source_path=""))
        with _merge_env(tmp_path):
            result = await build_merge_version(
                fake_db, plaza_id=5, source_skill_ids=[s.id, s.id], actor=admin
            )
        assert [x["skill_id"] for x in result["source_skills"]] == [251]


# ==================== publish / discard ====================


class TestPublishMerge:
    def _setup_publish(self, fake_db, tmp_path, *, holder_owner="dev02"):
        """场景①：原创 B 并入广场 A（A 当前快照为基线），并预置一个持有者副本（场景⑤口径）。"""
        plaza_dir = _write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# A base\n", "shared.md": "shared"})
        plaza = fake_db.seed(make_plaza(source_path=str(plaza_dir), source_checksum="b" * 64))
        b_dir = _write_pkg(tmp_path / "helper-b", {"SKILL.md": "# B merged\n", "new.md": "new"})
        primary = fake_db.seed(make_skill(
            id=301, skill_code="helper-b", origin="ORIGINAL", version="2.5.0",
            description="B 的最新描述", source_path=str(b_dir),
        ))
        holder = make_skill(
            id=311, skill_code="tool-a-holder", origin="PLAZA", plaza_id=5,
            inserted_by=holder_owner, status="ENABLED", share_status="shared",
        )
        fake_db.iteration_holders = [holder]
        return plaza, primary, holder

    async def _build(self, fake_db, admin, tmp_path, plaza_id, source_ids):
        with _merge_env(tmp_path):
            return await build_merge_version(
                fake_db, plaza_id=plaza_id, source_skill_ids=source_ids, actor=admin
            )

    async def test_发布全链路_场景1和5(self, fake_db, admin, tmp_path):
        plaza, primary, holder = self._setup_publish(fake_db, tmp_path, holder_owner="admin")
        with _merge_env(tmp_path) as env:  # build + publish 同一上下文，审计断言可对账两跳
            token = (
                await build_merge_version(
                    fake_db, plaza_id=plaza.id, source_skill_ids=[primary.id], actor=admin
                )
            )["merge_token"]
            row = [o for o in fake_db._added if isinstance(o, PmcpPlazaMerge)][0]
            temp_dir = Path(row.snapshot_path)
            assert temp_dir.is_dir()
            result = await publish_merge_version(
                fake_db, merge_token=token, action="publish", actor=admin, comment="工作台合并"
            )
        # 广场身份保持（场景①：code/name 不变）；description 取主源
        assert plaza.skill_code == "tool-a" and plaza.skill_name == "Tool A"
        assert plaza.description == "B 的最新描述"
        assert plaza.version == "1.0.1"  # +patch（设计⑤）
        assert plaza.status == "PUBLISHED"
        assert plaza.iteration_note == "工作台合并"
        assert plaza.source_path and "_plaza" in plaza.source_path.replace("\\", "/")
        assert (Path(plaza.source_path) / "SKILL.md").read_text(encoding="utf-8") == "# B merged\n"
        assert (Path(plaza.source_path) / "new.md").exists()
        assert (Path(plaza.source_path) / "shared.md").exists()  # 基线文件保留
        # 版本归档：source_version=主源提交人版本
        version_rows = [o for o in fake_db._added if isinstance(o, PmcpPlazaVersion)]
        assert len(version_rows) == 1
        assert version_rows[0].version == "1.0.1" and version_rows[0].source_version == "2.5.0"
        archive_dir = Path(version_rows[0].snapshot_path)
        assert (archive_dir / "SKILL.md").exists()
        # 场景⑤：admin 自持副本同样被置迭代态（无豁免）
        assert holder.status == "SHARE_ITERATION"
        assert result["status"] == "PUBLISHED" and result["holders_marked"] == 1
        assert row.status == "PUBLISHED"
        assert not temp_dir.exists()  # 临时包清理
        # 通知 skill_review 组（payload 含 skill_id/submitter/version）
        payload = env["notify"].await_args.args[1]
        assert payload["submitter"] == "dev01" and payload["version"] == "1.0.1"
        # 审计动作
        actions = [c.kwargs["extra_data"]["action"] for c in env["audit"].await_args_list]
        assert "merge_build" in actions and "merge_publish" in actions
        assert "mark_iteration" in actions

    async def test_场景4_裁决改判次源(self, fake_db, admin, tmp_path):
        plaza_dir = _write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# base v\n"})
        plaza = fake_db.seed(make_plaza(source_path=str(plaza_dir)))
        d1 = _write_pkg(tmp_path / "u1", {"SKILL.md": "# user1\n", "only1.md": "1"})
        d2 = _write_pkg(tmp_path / "u2", {"SKILL.md": "# user2\n", "only2.md": "2"})
        s1 = fake_db.seed(make_skill(id=321, source_path=str(d1)))
        s2 = fake_db.seed(make_skill(id=322, source_path=str(d2)))
        token = (await self._build(fake_db, admin, tmp_path, plaza.id, [s1.id, s2.id]))["merge_token"]
        row = [o for o in fake_db._added if isinstance(o, PmcpPlazaMerge)][0]
        temp_dir = Path(row.snapshot_path)
        with _merge_env(tmp_path):
            result = await publish_merge_version(
                fake_db, merge_token=token, action="publish", actor=admin,
                resolutions={"SKILL.md": s2.id},
            )
        assert not temp_dir.exists()
        assert (Path(plaza.source_path) / "SKILL.md").read_text(encoding="utf-8") == "# user2\n"
        conflict = result["conflicts"][0]
        assert conflict["resolution"] == s2.id

    async def test_裁决base回退保留基线内容(self, fake_db, admin, tmp_path):
        plaza_dir = _write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# base v\n"})
        plaza = fake_db.seed(make_plaza(source_path=str(plaza_dir)))
        d1 = _write_pkg(tmp_path / "u1", {"SKILL.md": "# user1\n"})
        d2 = _write_pkg(tmp_path / "u2", {"SKILL.md": "# user2\n"})
        s1 = fake_db.seed(make_skill(id=331, source_path=str(d1)))
        s2 = fake_db.seed(make_skill(id=332, source_path=str(d2)))
        token = (await self._build(fake_db, admin, tmp_path, plaza.id, [s1.id, s2.id]))["merge_token"]
        with _merge_env(tmp_path):
            await publish_merge_version(
                fake_db, merge_token=token, action="publish", actor=admin,
                resolutions={"SKILL.md": "base"},
            )
        assert (Path(plaza.source_path) / "SKILL.md").read_text(encoding="utf-8") == "# base v\n"

    async def test_裁决非冲突路径被拒(self, fake_db, admin, tmp_path):
        plaza = fake_db.seed(make_plaza(source_path=str(_write_pkg(tmp_path / "_plaza" / "5", {"SKILL.md": "# a\n"}))))
        s = fake_db.seed(make_skill(id=341, source_path=str(_write_pkg(tmp_path / "s", {"SKILL.md": "# s\n"}))))
        token = (await self._build(fake_db, admin, tmp_path, plaza.id, [s.id]))["merge_token"]
        with _merge_env(tmp_path):
            with pytest.raises(Exception) as ei:
                await publish_merge_version(
                    fake_db, merge_token=token, action="publish", actor=admin,
                    resolutions={"not-in-conflicts.md": "base"},
                )
        assert getattr(ei.value, "error_code", None) == CODE_INVALID_STATE

    async def test_终审严重违规阻断发布(self, fake_db, admin, tmp_path):
        plaza, primary, _holder = self._setup_publish(fake_db, tmp_path)
        token = (await self._build(fake_db, admin, tmp_path, plaza.id, [primary.id]))["merge_token"]
        row = [o for o in fake_db._added if isinstance(o, PmcpPlazaMerge)][0]
        blocked = {"passed": False, "critical_count": 2, "warning_count": 0, "suggestion_count": 0}
        with _merge_env(tmp_path) as env, patch(
            "platform_mcp.skills.merge_service._audit_summary_of", return_value=dict(blocked)
        ):
            with pytest.raises(Exception) as ei:
                await publish_merge_version(fake_db, merge_token=token, action="publish", actor=admin)
        assert getattr(ei.value, "error_code", None) == CODE_INVALID_STATE
        assert row.status == "BUILT"  # 未发布
        assert plaza.version == "1.0.0"  # 广场未变
        actions = [c.kwargs["extra_data"]["action"] for c in env["audit"].await_args_list]
        assert "merge_publish_blocked" in actions
        blocked_call = [c for c in env["audit"].await_args_list
                        if c.kwargs["extra_data"]["action"] == "merge_publish_blocked"][0]
        assert blocked_call.kwargs["result_status"] == "failed"

    async def test_discard_删临时包置态且二次操作被拒(self, fake_db, admin, tmp_path):
        plaza, primary, _holder = self._setup_publish(fake_db, tmp_path)
        token = (await self._build(fake_db, admin, tmp_path, plaza.id, [primary.id]))["merge_token"]
        row = [o for o in fake_db._added if isinstance(o, PmcpPlazaMerge)][0]
        temp_dir = Path(row.snapshot_path)
        with _merge_env(tmp_path):
            result = await publish_merge_version(fake_db, merge_token=token, action="discard", actor=admin)
        assert result["status"] == "DISCARDED"
        assert row.status == "DISCARDED" and not temp_dir.exists()
        assert plaza.version == "1.0.0"
        with _merge_env(tmp_path):
            with pytest.raises(Exception) as ei:
                await publish_merge_version(fake_db, merge_token=token, action="publish", actor=admin)
        assert getattr(ei.value, "error_code", None) == CODE_INVALID_STATE

    async def test_权限与token校验(self, fake_db, admin, non_admin, tmp_path):
        plaza, primary, _holder = self._setup_publish(fake_db, tmp_path)
        with _merge_env(tmp_path):
            with pytest.raises(Exception) as ei:
                await publish_merge_version(
                    fake_db, merge_token="nope", action="publish", actor=admin
                )
            assert getattr(ei.value, "error_code", None) == CODE_NOT_FOUND
            token = (await self._build(fake_db, admin, tmp_path, plaza.id, [primary.id]))["merge_token"]
            with pytest.raises(Exception) as ei2:
                await publish_merge_version(
                    fake_db, merge_token=token, action="publish", actor=non_admin
                )
            assert getattr(ei2.value, "error_code", None) == CODE_FORBIDDEN


class TestSerializeAndVersions:
    def test_serialize_merge字段齐备(self):
        row = PmcpPlazaMerge(
            merge_token="tok", plaza_id=5, source_skills=[{"skill_id": 1}],
            base_version="1.0.0", new_version="1.0.1", conflicts=[], audit_summary={"passed": True},
            snapshot_path="/x", status="BUILT", created_by="admin", inserted_by="admin", updated_by="admin",
        )
        data = serialize_merge(row)
        assert data["merge_token"] == "tok"
        assert data["status"] == "BUILT"
        assert set(data) >= {
            "merge_token", "plaza_id", "source_skills", "base_version", "new_version",
            "conflicts", "audit_summary", "snapshot_path", "status", "created_by", "created_at",
        }

    async def test_list_plaza_versions倒序与字段(self, fake_db):
        v2 = PmcpPlazaVersion(plaza_id=5, version="1.0.1", source_version="2.5.0", snapshot_path="/a",
                              checksum="c" * 64, file_manifest=[{"path": "SKILL.md"}],
                              audit_snapshot={"passed": True}, inserted_by="admin", updated_by="admin")
        v1 = PmcpPlazaVersion(plaza_id=5, version="1.0.0", source_version="1.0.0", snapshot_path="/b",
                              checksum="d" * 64, file_manifest=[], audit_snapshot={"passed": True},
                              inserted_by="admin", updated_by="admin")
        fake_db.execute = AsyncMock(  # type: ignore[assignment]
            return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [v2, v1]))
        )
        versions = await list_plaza_versions(fake_db, 5)
        assert versions[0]["version"] == "1.0.1"
        assert versions[0]["file_count"] == 1
        assert versions[1]["version"] == "1.0.0"
