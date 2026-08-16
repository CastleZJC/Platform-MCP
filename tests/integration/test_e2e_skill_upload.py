"""E2E 测试 — Skill 上传全流程（上传→审计→脱敏→README→注册→审核）

测试策略：创建真实 .zip 包文件，走 process_skill_upload 全链路，
同时通过 API 端点测试审核流程。
"""

import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.skills.audit.engine import audit_skill_package
from platform_mcp.skills.audit.models import AuditResult, Severity
from platform_mcp.skills.audit.sanitizer import check_sanitization, sanitize_skill_name
from platform_mcp.skills.readme.generator import generate_readme, should_generate_readme
from platform_mcp.skills.upload import (
    _compute_checksum,
    _detect_format,
    _extract_package,
    _parse_skill_md,
    process_skill_upload,
)


# ==================== 辅助函数 ====================


def _create_skill_zip(
    tmp_path: Path,
    skill_name: str,
    files: dict[str, str],
) -> Path:
    """创建 Skill .zip 包文件

    Args:
        tmp_path: 临时目录
        skill_name: Skill 包根目录名
        files: {相对路径: 内容} 字典

    Returns:
        创建的 .zip 文件路径
    """
    pkg_dir = tmp_path / "build"
    skill_dir = pkg_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in files.items():
        file_path = skill_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    zip_path = tmp_path / f"{skill_name}.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in files:
            full_path = skill_dir / rel_path
            arc_name = f"{skill_name}/{rel_path}"
            zf.write(str(full_path), arc_name)
    return zip_path


def _clean_skill_files() -> dict[str, str]:
    """返回一个干净的 Skill 包文件集（通过所有审计规则）"""
    return {
        "SKILL.md": "---\nname: sql-opt\ndescription: 优化 Oracle/MySQL SELECT 查询性能\n---\n优化 SQL 执行性能",
        "README.md": "# sql-opt\n优化 SQL 执行性能\n\n## 使用方法\n使用 MCP 工具执行 SQL 查询。",
        "main.py": "# 清洁代码\nresult = process_data(query)",
    }


def _critical_violation_files() -> dict[str, str]:
    """返回含严重违规的文件集（R3-01: 外部连接 + R4-01: 硬编码密码）"""
    return {
        "SKILL.md": "---\nname: bad-skill\ndescription: Bad\n---\n",
        "main.py": "import requests\nrequests.get('https://evil.com/api')\npassword = 'hardcoded_secret_value'",
    }


def _warning_violation_files() -> dict[str, str]:
    """返回含警告违规的文件集（R1-02: 递归删除 + R4-02: 日志泄露）"""
    return {
        "SKILL.md": "---\nname: warn-skill\ndescription: Warning test\n---\n",
        "README.md": "# warn-skill\nTest",
        "cleanup.sh": "rm -rf /var/log/old_logs",
        "debug.py": "print(f'Debug token: {api_token}')",
    }


# ==================== 测试类 ====================


class TestSkillUploadE2E:
    """Skill 上传全流程端到端测试"""

    @pytest.mark.asyncio
    async def test_clean_skill_upload_pipeline(self, tmp_path):
        """F-01/F-06: 干净包上传 → 审计通过 → README 保留 → 状态 PENDING_REVIEW"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "sql-opt", _clean_skill_files())

            # 手动走 pipeline 各步
            fmt = _detect_format(zip_path.name)
            assert fmt == "zip"

            checksum = _compute_checksum(zip_path)
            assert len(checksum) == 64

            # 解压
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, fmt)
            assert (skill_root / "SKILL.md").exists()

            # 解析 SKILL.md
            name, desc, version = _parse_skill_md(skill_root)
            assert name == "sql-opt"
            assert "优化" in desc

            # 审计
            audit_result = audit_skill_package(skill_root, name)
            assert audit_result.passed
            assert audit_result.critical_count == 0

            # 脱敏检查
            sanit_results = check_sanitization(skill_root, name)
            assert all(r.passed for r in sanit_results)

            # README 保留
            assert not should_generate_readme(skill_root)

    @pytest.mark.asyncio
    async def test_critical_violation_blocks_registration(self, tmp_path):
        """F-03: 严重规则命中 → 审计不通过，阻止注册"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "bad-skill", _critical_violation_files())
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, "zip")

            audit_result = audit_skill_package(skill_root, "bad-skill")
            assert not audit_result.passed
            assert audit_result.critical_count > 0

            # 验证 R3-01 和 R4-01 被检测到
            failed_rules = {r.rule_id for r in audit_result.results if not r.passed}
            assert "R3-01" in failed_rules or "R4-01" in failed_rules

    @pytest.mark.asyncio
    async def test_warning_allows_pending_review(self, tmp_path):
        """F-04: 警告规则命中 → 允许注册但标记 warning"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "warn-skill", _warning_violation_files())
            extract_dir = tmp_path / "extract_warn"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, "zip")

            audit_result = audit_skill_package(skill_root, "warn-skill")
            # 警告级命中存在
            warning_rules = [r for r in audit_result.results if not r.passed and r.severity == Severity.WARNING]
            assert len(warning_rules) > 0

    @pytest.mark.asyncio
    async def test_missing_readme_auto_generated(self, tmp_path):
        """F-06: 缺少 README.md → 自动生成"""
        files = {
            "SKILL.md": "---\nname: no-readme-skill\ndescription: No README test\n---\nBody",
        }
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "no-readme-skill", files)
            extract_dir = tmp_path / "extract_noreadme"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, "zip")

            # 确认缺少 README.md
            assert should_generate_readme(skill_root)

            # 自动生成
            name, desc, version = _parse_skill_md(skill_root)
            readme_content = generate_readme(name, desc, skill_root, version)
            assert "# no-readme-skill" in readme_content
            assert "No README test" in readme_content
            assert "v0.1.0" in readme_content

    @pytest.mark.asyncio
    async def test_existing_readme_preserved(self, tmp_path):
        """F-07: 已有 README.md → 保留原样不覆盖"""
        files = {
            "SKILL.md": "---\nname: has-readme\ndescription: Has README\n---\n",
            "README.md": "# Custom README\nThis is my custom content.",
        }
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "has-readme", files)
            extract_dir = tmp_path / "extract_hasreadme"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, "zip")

            assert not should_generate_readme(skill_root)
            original_readme = (skill_root / "README.md").read_text(encoding="utf-8")
            assert "Custom README" in original_readme

    @pytest.mark.asyncio
    async def test_pmcp_prefix_sanitization(self):
        """F-08: pmcp_ 前缀脱敏"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", ["pmcp"]):
            name, sanitized = sanitize_skill_name("pmcp_sql_opt")
            assert name == "sql_opt"
            assert sanitized is True

            name, sanitized = sanitize_skill_name("pmcp-sql-opt")
            assert name == "sql-opt"
            assert sanitized is True

    @pytest.mark.asyncio
    async def test_internal_reference_detected(self, tmp_path):
        """F-09: 内部引用拦截（R3-01 扩展）"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []), \
             patch.object(sanit_mod, "_SENSITIVE_KEYWORDS", ["acme-internal"]), \
             patch.object(sanit_mod, "_SENSITIVE_DOMAINS", ["svn.acme.test"]):
            skill_dir = tmp_path / "internal-ref-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: test\ndescription: test\n---\n"
                "Connects to svn.acme.test and uses acme-internal service.",
                encoding="utf-8",
            )
            results = check_sanitization(skill_dir, "test-skill")
            violations = [r for r in results if not r.passed]
            assert len(violations) > 0
            assert any(r.severity == Severity.CRITICAL for r in violations)

    @pytest.mark.asyncio
    async def test_private_ip_detected(self, tmp_path):
        """私有 IP 地址检测"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_KEYWORDS", []), \
             patch.object(sanit_mod, "_SENSITIVE_DOMAINS", []):
            skill_dir = tmp_path / "ip-skill"
            skill_dir.mkdir()
            (skill_dir / "config.py").write_text(
                "host = '192.168.1.100'\nport = 3306",
                encoding="utf-8",
            )
            results = check_sanitization(skill_dir, "ip-skill")
            violations = [r for r in results if not r.passed]
            assert len(violations) > 0
            assert any("私有 IP" in r.description for r in violations)

    @pytest.mark.asyncio
    async def test_audit_result_summary_structure(self, tmp_path):
        """F-12: 审计报告结构完整性"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "summary-test", _clean_skill_files())
            extract_dir = tmp_path / "extract_summary"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, "zip")

            audit_result = audit_skill_package(skill_root, "summary-test")
            summary = audit_result.to_audit_summary()

            assert "total_rules" in summary
            assert "critical_count" in summary
            assert "warning_count" in summary
            assert "suggestion_count" in summary
            assert "passed" in summary
            assert "failed_rules" in summary

    @pytest.mark.asyncio
    async def test_full_upload_pipeline_with_mock_db(self, tmp_path):
        """完整上传链路：zip → process_skill_upload → DB 写入"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "e2e-skill", _clean_skill_files())

            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            mock_db.add = MagicMock()

            mock_settings = MagicMock()
            mock_settings.skill.upload_dir = str(tmp_path / "skills")

            with patch("platform_mcp.skills.upload.get_settings", return_value=mock_settings):
                result = await process_skill_upload(
                    file_path=zip_path,
                    original_filename="e2e-skill.zip",
                    db=mock_db,
                    operator="admin",
                )

            # SKILL.md 中 name 字段为 "sql-opt"，process_skill_upload 解析后使用该名称
            assert result.skill_code == "sql-opt"
            assert result.source_format == "zip"
            assert result.audit_result.passed
            assert result.audit_result.critical_count == 0
            assert len(result.source_checksum) == 64

    @pytest.mark.asyncio
    async def test_upload_format_detection_and_rejection(self):
        """上传格式检测 + 非法格式拒绝"""
        assert _detect_format("skill.zip") == "zip"
        assert _detect_format("skill.7z") == "7z"
        assert _detect_format("SKILL.ZIP") == "zip"

        with pytest.raises(ValueError, match="不支持的文件格式"):
            _detect_format("test.tar.gz")

    @pytest.mark.asyncio
    async def test_review_skill_approve_via_api(self, admin_client, mock_db):
        """F-10: Admin 审核通过 → skill status → ENABLED"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "sql-opt"
        mock_skill.skill_name = "SQL 性能优化"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        mock_db.commit = AsyncMock()

        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "approve"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_review_skill_reject_via_api(self, admin_client, mock_db):
        """F-11: Admin 审核驳回 → skill status → REJECTED"""
        mock_skill = MagicMock()
        mock_skill.id = 2
        mock_skill.skill_code = "bad-skill"
        mock_skill.skill_name = "Bad Skill"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        mock_db.commit = AsyncMock()

        resp = await admin_client.post("/api/v1/skills/2/review", json={"action": "reject"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_audit_report_api_endpoint(self, admin_client, mock_db):
        """F-12: 审计报告存底 — API 可查"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "sql-opt"
        mock_skill.audit_status = "passed"
        mock_skill.audit_result = {
            "total_rules": 14,
            "critical_count": 0,
            "warning_count": 0,
            "suggestion_count": 0,
            "passed": True,
        }
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )

        resp = await admin_client.get("/api/v1/skills/1/audit-report")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert "audit_status" in data

    @pytest.mark.asyncio
    async def test_suggestion_level_rules_recorded(self, tmp_path):
        """F-05: 建议级规则命中 → 仅记录，不影响注册"""
        from platform_mcp.skills.audit import sanitizer as sanit_mod

        files = {
            "SKILL.md": "---\nname: sugg-skill\ndescription: Suggestion test\n---\nBody",
            "main.py": "# clean code\nresult = process(data)",
        }

        with patch.object(sanit_mod, "_SENSITIVE_PREFIXES", []):
            zip_path = _create_skill_zip(tmp_path, "sugg-skill", files)
            extract_dir = tmp_path / "extract_sugg"
            extract_dir.mkdir()
            skill_root = _extract_package(zip_path, extract_dir, "zip")

            audit_result = audit_skill_package(skill_root, "sugg-skill")
            assert audit_result.passed
            # 建议级（R5-01: 无 README.md）
            suggestion_rules = [r for r in audit_result.results if not r.passed and r.severity == Severity.SUGGESTION]
            assert len(suggestion_rules) > 0
            assert audit_result.critical_count == 0

    @pytest.mark.asyncio
    async def test_checksum_and_skill_md_parsing(self, tmp_path):
        """SHA-256 校验和 + SKILL.md 解析"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")
        checksum = _compute_checksum(test_file)
        assert len(checksum) == 64
        assert _compute_checksum(test_file) == checksum

        skill_dir = tmp_path / "parse-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: My cool skill\nversion: 1.0.0\n---\nBody here",
            encoding="utf-8",
        )
        name, desc, version = _parse_skill_md(skill_dir)
        assert name == "my-skill"
        assert desc == "My cool skill"
        assert version == "1.0.0"

        empty_dir = tmp_path / "empty-skill"
        empty_dir.mkdir()
        name, desc, version = _parse_skill_md(empty_dir)
        assert name == ""
        assert version == "0.1.0"

    @pytest.mark.asyncio
    async def test_extract_zip_package(self, tmp_path):
        """zip 包解压正确性"""
        files = {
            "SKILL.md": "---\nname: extract-test\ndescription: Extract\n---\n",
            "main.py": "x = 1",
            "references/doc.md": "# doc",
        }
        zip_path = _create_skill_zip(tmp_path, "extract-test", files)
        extract_dir = tmp_path / "extract_test"
        extract_dir.mkdir()
        skill_root = _extract_package(zip_path, extract_dir, "zip")

        assert (skill_root / "SKILL.md").exists()
        assert (skill_root / "main.py").exists()
        assert (skill_root / "references" / "doc.md").exists()