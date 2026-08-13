"""Skill 合规审计引擎单元测试 — 每条规则至少 2 个用例"""

import os
import tempfile
from pathlib import Path

import pytest

from platform_mcp.skills.audit.engine import (
    _check_r1_01,
    _check_r1_02,
    _check_r1_03,
    _check_r2_01,
    _check_r2_02,
    _check_r3_01,
    _check_r3_02,
    _check_r4_01,
    _check_r4_02,
    _check_r5_01,
    _check_r5_02,
    _check_r5_03,
    _check_r5_04,
    audit_skill_package,
    _rule_severity,
)
from platform_mcp.skills.audit.models import AuditResult, AuditRuleResult, Severity


# ==================== R1-01: 禁止修改 C 盘非 .claude 目录 ====================

class TestR101CDriveWrite:
    def test_c_drive_write_detected(self):
        content = 'open("C:\\Users\\admin\\data.txt", "w")'
        result = _check_r1_01("test.py", content)
        assert not result.passed
        assert result.rule_id == "R1-01"
        assert result.severity == Severity.CRITICAL

    def test_c_drive_claude_exempt(self):
        content = 'open("C:\\Users\\admin\\.claude\\skills\\data.txt", "w")'
        result = _check_r1_01("test.py", content)
        assert result.passed

    def test_no_c_drive_passes(self):
        content = 'open("/tmp/data.txt", "w")'
        result = _check_r1_01("test.py", content)
        assert result.passed


# ==================== R1-02: 递归删除 ====================

class TestR102RecursiveDelete:
    def test_rm_rf_detected(self):
        content = "os.system('rm -rf /var/log')"
        result = _check_r1_02("test.sh", content)
        assert not result.passed
        assert result.severity == Severity.WARNING

    def test_pycache_exempt(self):
        content = "shutil.rmtree('__pycache__')"
        result = _check_r1_02("test.py", content)
        assert result.passed

    def test_no_recursive_delete_passes(self):
        content = "os.remove('/tmp/single_file.txt')"
        result = _check_r1_02("test.py", content)
        assert result.passed


# ==================== R1-03: 禁止访问敏感文件 ====================

class TestR103SensitiveFiles:
    def test_env_file_detected(self):
        content = 'open(".env", "r")'
        result = _check_r1_03("test.py", content)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_ssh_key_detected(self):
        content = 'with open("~/.ssh/id_rsa") as f:'
        result = _check_r1_03("test.py", content)
        assert not result.passed

    def test_no_sensitive_file_passes(self):
        content = 'with open("config.yaml") as f:'
        result = _check_r1_03("test.py", content)
        assert result.passed


# ==================== R2-01: 禁止直连执行 DML/DDL ====================

class TestR201DmlDdl:
    def test_auto_execute_delete_detected(self):
        content = "cursor.execute('DELETE FROM users WHERE id = 1')"
        result = _check_r2_01("test.py", content)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_manual_script_exempt(self):
        content = """# 生成供人工审查的 SQL 脚本
cursor.execute('DELETE FROM temp_data')"""
        result = _check_r2_01("test.py", content)
        assert result.passed

    def test_select_only_passes(self):
        content = "cursor.execute('SELECT * FROM users')"
        result = _check_r2_01("test.py", content)
        assert result.passed


# ==================== R2-02: 禁止硬编码数据库连接信息 ====================

class TestR202DbConnection:
    def test_oracle_port_detected(self):
        content = "oracledb.connect(user='admin', password='xxx', dsn='host:1521/db')"
        result = _check_r2_02("test.py", content)
        assert not result.passed

    def test_jdbc_oracle_detected(self):
        content = 'jdbc:oracle:thin:@host:1521:sid'
        result = _check_r2_02("config.md", content)
        assert not result.passed

    def test_no_db_connection_passes(self):
        content = "db_conn = get_connection_from_env()"
        result = _check_r2_02("test.py", content)
        assert result.passed


# ==================== R3-01: 禁止外部 HTTP/HTTPS 连接 ====================

class TestR301ExternalHttp:
    def test_requests_get_detected(self):
        content = "requests.get('https://example.com/api')"
        result = _check_r3_01("test.py", content)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_curl_detected(self):
        content = "curl -X GET https://example.com"
        result = _check_r3_01("test.sh", content)
        assert not result.passed

    def test_no_http_request_passes(self):
        content = "result = local_function(data)"
        result = _check_r3_01("test.py", content)
        assert result.passed


# ==================== R3-02: 禁止网络监听 ====================

class TestR302NetworkListen:
    def test_socket_bind_detected(self):
        content = "sock.bind(('0.0.0.0', 8080))"
        result = _check_r3_02("test.py", content)
        assert not result.passed
        assert result.severity == Severity.WARNING

    def test_flask_run_detected(self):
        content = "app.run(host='0.0.0.0', port=5000)"
        result = _check_r3_02("test.py", content)
        assert not result.passed

    def test_no_listen_passes(self):
        content = "response = handle_request(data)"
        result = _check_r3_02("test.py", content)
        assert result.passed


# ==================== R4-01: 禁止硬编码密码/密钥/Token ====================

class TestR401HardcodedSecrets:
    def test_hardcoded_password_detected(self):
        content = "password = 'my_secret_pass'"
        result = _check_r4_01("test.py", content)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_placeholder_exempt(self):
        content = "password = '<password>'"
        result = _check_r4_01("test.py", content)
        assert result.passed

    def test_env_var_exempt(self):
        content = "password = '${DB_PASSWORD}'"
        result = _check_r4_01("test.py", content)
        assert result.passed


# ==================== R4-02: 禁止日志暴露敏感信息 ====================

class TestR402LogSensitive:
    def test_print_password_detected(self):
        content = "print(f'Password: {password}')"
        result = _check_r4_02("test.py", content)
        assert not result.passed
        assert result.severity == Severity.WARNING

    def test_logging_token_detected(self):
        content = 'logging.info(f"Token: {token}")'
        result = _check_r4_02("test.py", content)
        assert not result.passed

    def test_no_sensitive_log_passes(self):
        content = "logging.info('Process completed successfully')"
        result = _check_r4_02("test.py", content)
        assert result.passed


# ==================== R5-01: Skill 必须包含 README.md ====================

class TestR501Readme:
    def test_missing_readme(self):
        result = _check_r5_01(["SKILL.md", "main.py"])
        assert not result.passed
        assert result.severity == Severity.SUGGESTION

    def test_has_readme(self):
        result = _check_r5_01(["README.md", "SKILL.md", "main.py"])
        assert result.passed


# ==================== R5-02: SKILL.md frontmatter ====================

class TestR502SkillMd:
    def test_missing_skill_md(self):
        result = _check_r5_02(None)
        assert not result.passed
        assert result.severity == Severity.SUGGESTION

    def test_valid_frontmatter(self):
        content = "---\nname: sql-opt\ndescription: SQL optimization\n---\nBody here"
        result = _check_r5_02(content)
        assert result.passed

    def test_missing_name_field(self):
        content = "---\ndescription: Some desc\n---\nBody"
        result = _check_r5_02(content)
        assert not result.passed


# ==================== R5-03: 禁止硬编码用户路径 ====================

class TestR503UserPath:
    def test_hardcoded_users_path(self):
        content = 'path = "C:\\\\Users\\\\john\\\\data\\\\config.ini"'
        result = _check_r5_03("test.py", content)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_claude_path_exempt(self):
        content = 'path = "C:\\\\Users\\\\john\\\\.claude\\\\skills\\\\sql-opt"'
        result = _check_r5_03("test.py", content)
        assert result.passed

    def test_unix_home_passes(self):
        content = 'path = os.path.expanduser("~")'
        result = _check_r5_03("test.py", content)
        assert result.passed


# ==================== R5-04: 危险 shell 命令 ====================

class TestR504DangerousShell:
    def test_rm_rf_root_detected(self):
        content = "os.system('rm -rf /')"
        result = _check_r5_04("test.py", content)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_fork_bomb_detected(self):
        content = ":(){:|:&};:"
        result = _check_r5_04("test.sh", content)
        assert not result.passed

    def test_safe_command_passes(self):
        content = "os.system('ls -la /tmp')"
        result = _check_r5_04("test.py", content)
        assert result.passed


# ==================== audit_skill_package 集成测试 ====================

class TestAuditSkillPackage:
    def _create_skill_dir(self, tmp_path, files: dict, skill_name: str = "test-skill"):
        """创建临时 Skill 包目录"""
        skill_dir = tmp_path / skill_name
        skill_dir.mkdir()
        for rel_path, content in files.items():
            file_path = skill_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        return skill_dir

    def test_clean_skill_passes_all(self, tmp_path):
        """干净的 Skill 包应通过所有审计"""
        skill_dir = self._create_skill_dir(tmp_path, {
            "SKILL.md": "---\nname: test-skill\ndescription: A test skill\n---\nTest body",
            "README.md": "# test-skill\nA test skill.",
            "main.py": "# clean code\nresult = process(data)",
        })
        result = audit_skill_package(skill_dir, "test-skill")
        assert result.passed
        assert result.critical_count == 0

    def test_skill_with_violations_fails(self, tmp_path):
        """含违规的 Skill 包应被标记"""
        skill_dir = self._create_skill_dir(tmp_path, {
            "SKILL.md": "---\nname: bad-skill\ndescription: Bad\n---\n",
            "main.py": "requests.get('https://evil.com')\npassword = 'hardcoded_secret'",
        })
        result = audit_skill_package(skill_dir, "bad-skill")
        assert not result.passed
        assert result.critical_count > 0

    def test_result_to_audit_summary(self, tmp_path):
        """to_audit_summary 应返回正确结构"""
        skill_dir = self._create_skill_dir(tmp_path, {
            "SKILL.md": "---\nname: summary-test\ndescription: Summary\n---\n",
            "README.md": "# test",
        })
        result = audit_skill_package(skill_dir, "summary-test")
        summary = result.to_audit_summary()
        assert "total_rules" in summary
        assert "critical_count" in summary
        assert "warning_count" in summary
        assert "suggestion_count" in summary
        assert "passed" in summary


# ==================== _rule_severity 辅助函数 ====================

class TestRuleSeverity:
    def test_critical_rules(self):
        for rid in ("R1-01", "R1-03", "R2-01", "R2-02", "R3-01", "R4-01", "R5-03", "R5-04"):
            assert _rule_severity(rid) == Severity.CRITICAL

    def test_warning_rules(self):
        for rid in ("R1-02", "R3-02", "R4-02"):
            assert _rule_severity(rid) == Severity.WARNING

    def test_suggestion_rules(self):
        for rid in ("R5-01", "R5-02"):
            assert _rule_severity(rid) == Severity.SUGGESTION


# ==================== Sanitizer 测试 ====================

from platform_mcp.skills.audit import sanitizer as sanit_mod
from platform_mcp.skills.audit.sanitizer import sanitize_skill_name, check_sanitization


class TestSanitizeSkillName:
    def test_configured_prefix_removed(self, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_PREFIXES", ["demo"])
        name, sanitized = sanitize_skill_name("demo_sql_opt")
        assert name == "sql_opt"
        assert sanitized is True

    def test_configured_dash_prefix_removed(self, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_PREFIXES", ["demo"])
        name, sanitized = sanitize_skill_name("demo-sql-opt")
        assert name == "sql-opt"
        assert sanitized is True

    def test_no_matching_prefix_unchanged(self, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_PREFIXES", ["demo"])
        name, sanitized = sanitize_skill_name("sql_opt")
        assert name == "sql_opt"
        assert sanitized is False

    def test_no_prefixes_configured_passes_all(self, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_PREFIXES", [])
        name, sanitized = sanitize_skill_name("anything_here")
        assert name == "anything_here"
        assert sanitized is False


class TestCheckSanitization:
    def test_configured_keyword_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_KEYWORDS", ["acme-internal"])
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\nUses acme-internal service"
        )
        results = check_sanitization(skill_dir, "test-skill")
        violations = [r for r in results if not r.passed]
        assert len(violations) > 0
        assert any("内部引用" in r.description for r in violations)

    def test_configured_domain_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_DOMAINS", ["corp.acme.test"])
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "config.py").write_text("host = 'db.corp.acme.test'")
        results = check_sanitization(skill_dir, "test-skill")
        violations = [r for r in results if not r.passed]
        assert len(violations) > 0
        assert any("内部域名" in r.description for r in violations)

    def test_private_ip_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_KEYWORDS", [])
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_DOMAINS", [])
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "config.py").write_text("host = '192.168.1.100'")
        results = check_sanitization(skill_dir, "test-skill")
        violations = [r for r in results if not r.passed]
        assert len(violations) > 0
        assert any("私有 IP" in r.description for r in violations)

    def test_clean_skill_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_KEYWORDS", [])
        monkeypatch.setattr(sanit_mod, "_SENSITIVE_DOMAINS", [])
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test\ndescription: clean\n---\npublic.example.com")
        results = check_sanitization(skill_dir, "test-skill")
        violations = [r for r in results if not r.passed]
        assert len(violations) == 0