"""单元测试 — scripts/_rollback_plaza_version.py 脚本壳（批次4 回滚开放，2026-09-11）

脚本已服务化：CLI 壳仅做预检（plaza / 版本归档 / 快照目录），实际变更委托
``plaza_service.rollback_plaza_version``（与 Web POST /plaza/{id}/versions/{version}/rollback
同一编排），脚本自行 commit。本文件验证委托链路与 --dry-run 不触碰服务。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("rollback_script", _ROOT / "scripts" / "_rollback_plaza_version.py")


@pytest.fixture
def script():
    assert _SPEC is not None and _SPEC.loader is not None
    module = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(module)  # module_from_spec 不执行模块体，须显式 exec
    return module


class _FakeCtx:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def _fake_session(plaza, version_row):
    session = MagicMock()
    session.get = AsyncMock(return_value=plaza)
    result = MagicMock()
    result.scalar_one_or_none.return_value = version_row
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


def _install(script, session, monkeypatch):
    monkeypatch.setattr(script, "_ensure_engine", MagicMock())
    # 脚本调用形态：get_session_factory()() 再 async with（工厂 → 会话制造器 → 上下文）
    maker = MagicMock(return_value=_FakeCtx(session))
    monkeypatch.setattr(script, "get_session_factory", MagicMock(return_value=maker))


class TestRollbackScript:
    def _plaza(self):
        from platform_mcp.skills.models import PmcpSkillPlaza

        return PmcpSkillPlaza(id=5, skill_code="oracle-backup", skill_name="Oracle 备份", version="1.0")

    def _version_row(self, tmp_path):
        from platform_mcp.skills.models import PmcpPlazaVersion

        snap = tmp_path / "_plaza_versions" / "5" / "0.9.0"
        snap.mkdir(parents=True)
        (snap / "SKILL.md").write_text("# archived", encoding="utf-8")
        return PmcpPlazaVersion(
            id=11, plaza_id=5, version="0.9.0", snapshot_path=str(snap),
            file_manifest=[{"path": "SKILL.md"}],
        )

    @pytest.mark.asyncio
    async def test_实跑委托服务并提交(self, script, monkeypatch, tmp_path, capsys):
        plaza = self._plaza()
        row = self._version_row(tmp_path)
        session = _fake_session(plaza, row)
        _install(script, session, monkeypatch)
        svc = AsyncMock(return_value={
            "plaza_id": 5, "skill_code": "oracle-backup", "from_version": "1.0",
            "to_version": "0.9.0", "file_count": 1, "holders_marked": 0,
        })
        monkeypatch.setattr(script, "rollback_plaza_version", svc)
        monkeypatch.setattr(sys, "argv", ["prog", "--plaza-id", "5", "--version", "0.9.0", "--note", "修复误发布"])
        await script.main()
        svc.assert_awaited_once()
        # 委托参数：session + 路径参数 + admin 脚本身份 + note 透传 + channel=script
        assert svc.await_args.args[1:4] == (5, "0.9.0", script._SCRIPT_ACTOR)
        assert script._SCRIPT_ACTOR.is_admin
        assert svc.await_args.kwargs["note"] == "修复误发布"
        assert svc.await_args.kwargs["channel"] == "script"
        session.commit.assert_awaited_once()
        out = capsys.readouterr().out
        assert "回退完成" in out

    @pytest.mark.asyncio
    async def test_dry_run不触碰服务不提交(self, script, monkeypatch, tmp_path, capsys):
        plaza = self._plaza()
        row = self._version_row(tmp_path)
        session = _fake_session(plaza, row)
        _install(script, session, monkeypatch)
        svc = AsyncMock()
        monkeypatch.setattr(script, "rollback_plaza_version", svc)
        monkeypatch.setattr(sys, "argv", ["prog", "--plaza-id", "5", "--version", "0.9.0", "--dry-run"])
        await script.main()
        svc.assert_not_awaited()
        session.commit.assert_not_awaited()
        assert "dry-run" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_快照目录缺失中止(self, script, monkeypatch, tmp_path):
        import shutil

        plaza = self._plaza()
        row = self._version_row(tmp_path)
        shutil.rmtree(row.snapshot_path)
        session = _fake_session(plaza, row)
        _install(script, session, monkeypatch)
        svc = AsyncMock()
        monkeypatch.setattr(script, "rollback_plaza_version", svc)
        monkeypatch.setattr(sys, "argv", ["prog", "--plaza-id", "5", "--version", "0.9.0"])
        with pytest.raises(SystemExit):
            await script.main()
        svc.assert_not_awaited()
