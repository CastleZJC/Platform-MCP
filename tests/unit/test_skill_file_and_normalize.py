"""单元测试 — get_skill_file 包内文件下发 + 绝对路径自动调整（2026-09-08）

① ``_read_package_file``：防穿越 / utf-8 与 base64 双编码 / sha256；
② ``normalize_package_paths``：包内引用改相对（reference）、工作路径改当前路径（workdir）、
URL 不动、幂等；③ 注册链路版本一致：调整记录随 DraftBuildResult 返回。
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from platform_mcp.review.service import SkillReviewError
from platform_mcp.skills.ecosystem.draft import build_draft_content
from platform_mcp.skills.ecosystem.plaza_tools import _read_package_file
from platform_mcp.skills.normalize import normalize_package_paths


def test_读取文本与二进制(tmp_path):
    (tmp_path / "SKILL.md").write_text("# 你好\n", encoding="utf-8", newline="\n")
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "logo.png").write_bytes(b"\x89PNG-bin")
    text_file = _read_package_file(str(tmp_path), "SKILL.md")
    assert text_file["encoding"] == "utf-8" and text_file["content"] == "# 你好\n"
    bin_file = _read_package_file(str(tmp_path), "img/logo.png")
    assert bin_file["encoding"] == "base64"
    assert base64.b64decode(bin_file["content"]) == b"\x89PNG-bin"
    assert bin_file["sha256"] == hashlib.sha256(b"\x89PNG-bin").hexdigest()


def test_路径穿越与缺失被拒(tmp_path):
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    with pytest.raises(SkillReviewError):
        _read_package_file(str(tmp_path), "../outside.md")
    with pytest.raises(SkillReviewError):
        _read_package_file(str(tmp_path), "/abs.md")
    with pytest.raises(SkillReviewError):
        _read_package_file(str(tmp_path), "missing.md")


def test_绝对路径引用改包内相对_工作路径改当前路径(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "oracle.md").write_text("# oracle\n", encoding="utf-8")
    (tmp_path / "SKILL.md").write_text(
        "详见 D:\\work\\skills\\sql_opt\\references\\oracle.md；"
        "报告输出到 /home/dev/report/out.md；参考 https://example.com/home/docs 不动\n",
        encoding="utf-8", newline="\n",
    )
    adjustments = normalize_package_paths(tmp_path)
    text = (tmp_path / "SKILL.md").read_text(encoding="utf-8")
    assert "references/oracle.md" in text and "D:\\work" not in text
    assert "./out.md" in text and "/home/dev" not in text
    assert "https://example.com/home/docs" in text  # URL 不动
    by_kind = {a["kind"]: a for a in adjustments}
    assert by_kind["reference"]["after"] == "references/oracle.md"
    assert by_kind["workdir"]["after"] == "./out.md"
    # 幂等：再跑零调整
    assert normalize_package_paths(tmp_path) == []


def test_注册链路携带调整记录(tmp_path):
    """build_draft_content 内联 normalize：SKILL.md 含绝对路径时 DraftBuildResult 返回调整记录。"""
    from unittest.mock import MagicMock, patch

    from platform_mcp.skills.audit.models import AuditResult

    settings_mock = MagicMock()
    settings_mock.skill.upload_dir = str(tmp_path / "store")
    skill_md = (
        "---\nname: demo\n---\n# Demo\n"
        "模板见 C:\\pkg\\refs\\a.md\n"
    )
    with patch("platform_mcp.skills.ecosystem.draft.get_settings", return_value=settings_mock):
        with patch("platform_mcp.skills.ecosystem.draft.audit_skill_package") as audit_mock:
            audit_mock.return_value = AuditResult(skill_name="demo")
            result = build_draft_content(
                skill_code="norm", skill_name="Demo", description="d",
                skill_md=skill_md, version="0.1.0",
                attachments=[("refs/a.md", b"# a\n")],
            )
    assert result.path_adjustments and result.path_adjustments[0]["kind"] == "reference"
    assert result.path_adjustments[0]["after"] == "refs/a.md"
    stored = (tmp_path / "store" / "norm" / "SKILL.md").read_text(encoding="utf-8")
    assert "refs/a.md" in stored and "C:\\pkg" not in stored
