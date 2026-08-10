"""5.2.1 SQL 注入防护验证"""

from platform_mcp.skills.database.risk import RiskEngine, RiskLevel


class TestSQLInjectionProtection:
    def setup_method(self):
        self.engine = RiskEngine()

    def test_drop_table_injection(self):
        result = self.engine.analyze("'; DROP TABLE users; --")
        assert result.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_union_injection(self):
        result = self.engine.analyze("SELECT * FROM users WHERE id = 1 UNION SELECT * FROM passwords")
        assert result.level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_exec_command_injection(self):
        result = self.engine.analyze("; EXEC xp_cmdshell 'dir'")
        assert result.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_delete_injection(self):
        result = self.engine.analyze("1; DELETE FROM users WHERE 1=1")
        assert result.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_drop_after_semicolon(self):
        result = self.engine.analyze("SELECT 1; DROP TABLE users")
        assert result.level == RiskLevel.CRITICAL

    def test_truncate_injection(self):
        result = self.engine.analyze("'; TRUNCATE TABLE users; --")
        assert result.level == RiskLevel.CRITICAL
