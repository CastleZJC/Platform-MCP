"""单元测试 — 广场版本归档（manifest / snapshot / upsert / backfill，2026-09-08）

文件级版本管理仅限广场 Skill（用户裁决）：approve/merge 快照到
``_plaza_versions/{plaza_id}/{version}/`` + 清单落 ``pmcp_plaza_version``；
同版本重发布覆盖（与 pmcp_skill_version 同语义），个人/系统 Skill 仅最新版不参与。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from platform_mcp.review.service import (
    archive_plaza_version,
    backfill_plaza_versions,
    build_file_manifest,
)
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillPlaza


class _RowsResult:
    """伪 execute 结果：scalars().all() 与 scalar_one_or_none() 双兼容。"""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> "_RowsResult":
        return self

    def all(self) -> list:
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _SeqDB:
    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.added: list = []
        self.flush_count = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

    async def execute(self, stmt):  # noqa: ARG002
        return self._results.pop(0)


def test_文件清单排序与哈希(tmp_path):
    (tmp_path / "refs").mkdir()
    (tmp_path / "SKILL.md").write_text("# s\n", encoding="utf-8")
    (tmp_path / "refs" / "a.md").write_bytes(b"aaa")
    manifest = build_file_manifest(tmp_path)
    assert [m["path"] for m in manifest] == ["SKILL.md", "refs/a.md"]
    assert manifest[1]["size"] == 3
    assert len(manifest[1]["sha256"]) == 64


async def test_归档快照落盘并同版本upsert覆盖(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("# v\n", encoding="utf-8")
    settings_mock = MagicMock()
    settings_mock.skill.upload_dir = str(tmp_path / "store")
    existing = PmcpPlazaVersion(plaza_id=1, version="0.1.0")
    db = _SeqDB([_RowsResult([]), _RowsResult([existing])])
    with patch("platform_mcp.review.service.get_settings", return_value=settings_mock):
        first = await archive_plaza_version(
            db, plaza_id=1, version="0.1.0", source_path=str(src),
            checksum="c1", audit_snapshot={"passed": True}, operator="admin",
        )
        second = await archive_plaza_version(
            db, plaza_id=1, version="0.1.0", source_path=str(src),
            checksum="c2", audit_snapshot={"passed": True}, operator="admin",
        )
    assert db.added == [first]                    # 仅首次插入，重发布覆盖既有行
    assert second is existing and existing.checksum == "c2"
    assert (tmp_path / "store" / "_plaza_versions" / "1" / "0.1.0" / "SKILL.md").exists()
    assert existing.file_manifest[0]["path"] == "SKILL.md"


async def test_无源码包仅落DB行(tmp_path):
    db = _SeqDB([_RowsResult([])])
    record = await archive_plaza_version(
        db, plaza_id=9, version="0.2.0", source_path=None,
        checksum=None, audit_snapshot=None, operator="x",
    )
    assert db.added == [record]
    assert record.snapshot_path == "" and record.file_manifest == []


async def test_存量广场补一版并跳过已有(tmp_path):
    src = tmp_path / "p"
    src.mkdir()
    (src / "SKILL.md").write_text("# p\n", encoding="utf-8")
    settings_mock = MagicMock()
    settings_mock.skill.upload_dir = str(tmp_path / "store")
    plaza = PmcpSkillPlaza(
        id=5, skill_code="p5", skill_name="P5", version="1.0.0", source_path=str(src)
    )
    with patch("platform_mcp.review.service.get_settings", return_value=settings_mock):
        db = _SeqDB([
            _RowsResult([plaza]),   # 广场扫描
            _RowsResult([]),        # 无版本归档 → 补一版
            _RowsResult([]),        # archive 内部 select（insert 分支）
        ])
        assert await backfill_plaza_versions(db) == 1
        assert db.added and db.added[0].version == "1.0.0"

        db2 = _SeqDB([_RowsResult([plaza]), _RowsResult([77])])  # 已有版本 → 跳过
        assert await backfill_plaza_versions(db2) == 0
        assert db2.added == []
