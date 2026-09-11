"""单元测试 — README 迭代段落服务（设计定稿⑥，2026-09-10）

覆盖：append_or_refresh_section 幂等（追加/替换/空文）/ 广场权威链渲染（发布与合并类型、
manifest diff 单元格、当前生效版本与回滚标注）/ 个人版本史参考表 / 广场 README 重生成
（无 README 创建、含 README 幂等替换、无源目录 False）/ 启动补历史（缺段落补齐、
含标记跳过、无目录跳过、逐条隔离）。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from platform_mcp.skills.iteration_readme import (
    ITERATION_SECTION_MARKER,
    append_or_refresh_section,
    backfill_readme_iterations,
    refresh_plaza_readme_iteration,
    render_personal_iteration_section,
    render_plaza_iteration_section,
)
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillVersion


class FakeDB:
    """按表名分派查询结果：广场版本行 / merge new_version 集 / 个人版本行 / 广场与个人扫描行。"""

    def __init__(
        self,
        *,
        plaza_versions: list | None = None,
        merged_versions: list | None = None,
        personal_versions: list | None = None,
        plazas: list | None = None,
        skills: list | None = None,
    ) -> None:
        self.plaza_versions = plaza_versions or []
        self.merged_versions = merged_versions or []
        self.personal_versions = personal_versions or []
        self.plazas = plazas or []
        self.skills = skills or []

    async def execute(self, stmt):
        sql = str(stmt)
        result = MagicMock()
        if "pmcp_plaza_merge" in sql:
            result.scalars.return_value.all.return_value = list(self.merged_versions)
        elif "pmcp_plaza_version" in sql:
            result.scalars.return_value.all.return_value = list(self.plaza_versions)
        elif "pmcp_skill_plaza" in sql:
            result.scalars.return_value.all.return_value = list(self.plazas)
        elif "pmcp_skill_version" in sql:
            result.scalars.return_value.all.return_value = list(self.personal_versions)
        else:  # pmcp_skill 扫描（backfill 个人段，origin=ORIGINAL 过滤）
            result.scalars.return_value.all.return_value = list(self.skills)
        return result


# ==================== append_or_refresh_section（幂等）====================


def test_末尾追加():
    base = "# 标题\n\n正文"
    out = append_or_refresh_section(base, f"{ITERATION_SECTION_MARKER}\n第一版")
    assert out == f"{base}\n\n{ITERATION_SECTION_MARKER}\n第一版"


def test_含标记幂等替换():
    first = append_or_refresh_section("# T", f"{ITERATION_SECTION_MARKER}\n第一版")
    second = append_or_refresh_section(first, f"{ITERATION_SECTION_MARKER}\n第二版")
    assert second == f"# T\n\n{ITERATION_SECTION_MARKER}\n第二版"
    assert second.count(ITERATION_SECTION_MARKER) == 1


def test_空文本仅返回段落():
    assert append_or_refresh_section("", "S") == "S"
    assert append_or_refresh_section(None, "S") == "S"


# ==================== 广场权威链渲染 ====================


def _pv(version: str, *, source_version: str | None = None, by: str = "dev01",
        day: tuple[int, int] = (9, 10), manifest: list | None = None) -> PmcpPlazaVersion:
    return PmcpPlazaVersion(
        plaza_id=5, version=version, source_version=source_version or version,
        inserted_by=by, inserted_at=datetime(2026, *day, 8, 0, 0), file_manifest=manifest or [],
    )


async def test_广场段落_发布与合并类型_diff与当前版本():
    v1 = _pv("1.0.0", manifest=[{"path": "SKILL.md", "size": 10, "sha256": "a"}])
    v2 = _pv(
        "1.0.1", source_version="2.0.0", by="admin", day=(9, 11),
        manifest=[
            {"path": "SKILL.md", "size": 12, "sha256": "b"},
            {"path": "refs/x.md", "size": 3, "sha256": "c"},
        ],
    )
    db = FakeDB(plaza_versions=[v1, v2], merged_versions=["1.0.1"])
    section = await render_plaza_iteration_section(db, 5, "1.0.1")
    assert section.startswith(ITERATION_SECTION_MARKER)
    assert "| 1.0.0 | 发布 | 1.0.0 | dev01 | 2026-09-10 | 新增 1 / 修改 0 / 删除 0" in section
    assert "| 1.0.1 | 合并 | 2.0.0 | admin | 2026-09-11 | 新增 1 / 修改 1 / 删除 0" in section
    assert "refs/x.md" in section  # diff 样例文件名
    assert "当前生效版本：**1.0.1**" in section
    assert "回滚" not in section


async def test_广场段落_回滚标注():
    db = FakeDB(plaza_versions=[_pv("1.0.0")])
    section = await render_plaza_iteration_section(db, 5, "0.9.0")
    assert "当前生效版本：**0.9.0**（回滚生效，非最新归档版）" in section


# ==================== 个人版本史参考表 ====================


async def test_个人段落_版本史参考表():
    row = PmcpSkillVersion(
        skill_id=1, version="0.1.0", generated_by="template",
        inserted_at=datetime(2026, 9, 10, 9, 0, 0),
    )
    section = await render_personal_iteration_section(FakeDB(personal_versions=[row]), 1)
    assert "版本迭代记录（个人存档参考）" in section
    assert "| 0.1.0 | 2026-09-10 | template |" in section


# ==================== 广场 README 重生成 ====================


async def test_广场重生成_创建与幂等替换(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("# s\n", encoding="utf-8")
    (pkg / "README.md").write_text("# 原 README\n", encoding="utf-8")
    plaza = SimpleNamespace(id=5, version="1.0.0", source_path=str(pkg))
    db = FakeDB(plaza_versions=[_pv("1.0.0")])

    assert await refresh_plaza_readme_iteration(db, plaza) is True
    text1 = (pkg / "README.md").read_text(encoding="utf-8")
    assert text1.startswith("# 原 README")
    assert text1.count(ITERATION_SECTION_MARKER) == 1

    await refresh_plaza_readme_iteration(db, plaza)  # 再发布：幂等替换（标记恒 1）
    text2 = (pkg / "README.md").read_text(encoding="utf-8")
    assert text2.startswith("# 原 README")
    assert text2.count(ITERATION_SECTION_MARKER) == 1


async def test_广场重生成_无README时以段落创建(tmp_path):
    pkg = tmp_path / "pkg2"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("# s\n", encoding="utf-8")
    plaza = SimpleNamespace(id=5, version="1.0.0", source_path=str(pkg))
    assert await refresh_plaza_readme_iteration(FakeDB(plaza_versions=[_pv("1.0.0")]), plaza) is True
    text = (pkg / "README.md").read_text(encoding="utf-8")
    assert text.startswith(ITERATION_SECTION_MARKER)


async def test_广场重生成_无源目录返回False():
    plaza = SimpleNamespace(id=5, version="1.0.0", source_path=None)
    assert await refresh_plaza_readme_iteration(FakeDB(), plaza) is False


# ==================== 启动补历史 ====================


async def test_补历史_补齐缺段_跳过含标记与无目录(tmp_path):
    pkg_p = tmp_path / "plaza"   # 广场缺段 → 补
    pkg_p.mkdir()
    (pkg_p / "README.md").write_text("# p\n", encoding="utf-8")
    pkg_p2 = tmp_path / "plaza2"  # 广场已含标记 → 跳过
    pkg_p2.mkdir()
    (pkg_p2 / "README.md").write_text(f"# p2\n\n{ITERATION_SECTION_MARKER}\n已有\n", encoding="utf-8")
    pkg_s = tmp_path / "skill"   # 个人 ORIGINAL 缺段 → 补
    pkg_s.mkdir()
    (pkg_s / "README.md").write_text("# s\n", encoding="utf-8")

    plazas = [
        SimpleNamespace(id=1, version="1.0.0", source_path=str(pkg_p)),
        SimpleNamespace(id=2, version="1.0.0", source_path=str(pkg_p2)),
        SimpleNamespace(id=3, version="1.0.0", source_path=None),  # 无目录 → 跳过
    ]
    skills = [SimpleNamespace(id=11, origin="ORIGINAL", source_path=str(pkg_s))]
    counts = await backfill_readme_iterations(FakeDB(plazas=plazas, skills=skills))
    assert counts == {"plaza": 1, "personal": 1}
    assert ITERATION_SECTION_MARKER in (pkg_p / "README.md").read_text(encoding="utf-8")
    assert (pkg_p2 / "README.md").read_text(encoding="utf-8") == f"# p2\n\n{ITERATION_SECTION_MARKER}\n已有\n"
    assert ITERATION_SECTION_MARKER in (pkg_s / "README.md").read_text(encoding="utf-8")

    # 幂等：再跑一遍全部跳过
    assert await backfill_readme_iterations(FakeDB(plazas=plazas, skills=skills)) == {"plaza": 0, "personal": 0}
