"""5.1.1 RiskEngine 单元测试 — LOW/MEDIUM/HIGH/CRITICAL 四级"""

from platform_mcp.skills.database.risk import RiskEngine, RiskLevel, RiskResult


class TestRiskEngineAnalyze:
    def setup_method(self):
        self.engine = RiskEngine()

    def test_analyze_select_returns_low(self):
        result = self.engine.analyze("SELECT * FROM users")
        assert result.level == RiskLevel.LOW
        assert result.statement_type == "SELECT"

    def test_analyze_insert_returns_medium(self):
        result = self.engine.analyze("INSERT INTO users (id, name) VALUES (1, 'test')")
        assert result.level == RiskLevel.MEDIUM
        assert result.statement_type == "INSERT"

    def test_analyze_update_without_where_returns_high(self):
        result = self.engine.analyze("UPDATE users SET status = 0")
        assert result.level == RiskLevel.HIGH
        assert "DELETE/UPDATE 无 WHERE 子句" in result.reasons

    def test_analyze_delete_without_where_returns_high(self):
        result = self.engine.analyze("DELETE FROM users")
        assert result.level == RiskLevel.HIGH

    def test_analyze_delete_with_where_returns_medium(self):
        result = self.engine.analyze("DELETE FROM users WHERE id = 1")
        assert result.level == RiskLevel.MEDIUM

    def test_analyze_update_with_where_returns_medium(self):
        result = self.engine.analyze("UPDATE users SET name = 'a' WHERE id = 1")
        assert result.level == RiskLevel.MEDIUM

    def test_analyze_drop_table_returns_critical(self):
        result = self.engine.analyze("DROP TABLE users")
        assert result.level == RiskLevel.CRITICAL
        assert any("DROP" in r for r in result.reasons)

    def test_analyze_truncate_returns_critical(self):
        result = self.engine.analyze("TRUNCATE TABLE users")
        assert result.level == RiskLevel.CRITICAL

    def test_analyze_alter_returns_high(self):
        result = self.engine.analyze("ALTER TABLE users ADD COLUMN age INT")
        assert result.level == RiskLevel.HIGH
        assert result.statement_type == "ALTER"

    def test_analyze_create_returns_high(self):
        result = self.engine.analyze("CREATE TABLE test (id INT)")
        assert result.level == RiskLevel.HIGH

    def test_analyze_empty_sql_returns_low(self):
        result = self.engine.analyze("")
        assert result.level == RiskLevel.LOW
        assert result.statement_type == "EMPTY"

    def test_analyze_whitespace_sql_returns_low(self):
        result = self.engine.analyze("   \n\t  ")
        assert result.level == RiskLevel.LOW
        assert result.statement_type == "EMPTY"

    def test_analyze_exec_call_returns_high(self):
        result = self.engine.analyze("EXEC sp_rename 'users', 'users_old'")
        assert result.level == RiskLevel.HIGH
        assert any("存储过程调用" in r for r in result.reasons)

    def test_analyze_prod_env_select_stays_low(self):
        result = self.engine.analyze("SELECT * FROM users", env_code="PROD")
        assert result.level == RiskLevel.LOW

    def test_analyze_prod_env_drop_stays_critical(self):
        result = self.engine.analyze("DROP TABLE users", env_code="PROD")
        assert result.level == RiskLevel.CRITICAL

    def test_analyze_prod_env_insert_stays_medium(self):
        result = self.engine.analyze("INSERT INTO users VALUES (1,'a')", env_code="PROD")
        assert result.level == RiskLevel.MEDIUM

    def test_needs_confirm_true_for_high_and_critical(self):
        assert RiskResult(level=RiskLevel.HIGH, statement_type="DELETE").needs_confirm is True
        assert RiskResult(level=RiskLevel.CRITICAL, statement_type="DROP").needs_confirm is True

    def test_needs_confirm_false_for_low_and_medium(self):
        assert RiskResult(level=RiskLevel.LOW, statement_type="SELECT").needs_confirm is False
        assert RiskResult(level=RiskLevel.MEDIUM, statement_type="INSERT").needs_confirm is False

    def test_analyze_prod_env_create_upgraded_to_critical(self):
        result = self.engine.analyze("CREATE TABLE test (id INT)", env_code="PROD")
        assert result.level == RiskLevel.CRITICAL
        assert "生产库 DDL 操作强制 CRITICAL" in result.reasons

    def test_analyze_prod_env_alter_upgraded_to_critical(self):
        result = self.engine.analyze("ALTER TABLE users ADD COLUMN age INT", env_code="PROD")
        assert result.level == RiskLevel.CRITICAL
        assert "生产库 DDL 操作强制 CRITICAL" in result.reasons

    def test_analyze_prod_env_delete_without_where_upgraded_to_critical(self):
        result = self.engine.analyze("DELETE FROM users", env_code="PROD")
        assert result.level == RiskLevel.CRITICAL
        assert "生产库无 WHERE 的 DELETE/UPDATE 强制 CRITICAL" in result.reasons

    def test_analyze_prod_env_update_without_where_upgraded_to_critical(self):
        result = self.engine.analyze("UPDATE users SET status = 0", env_code="PROD")
        assert result.level == RiskLevel.CRITICAL
        assert "生产库无 WHERE 的 DELETE/UPDATE 强制 CRITICAL" in result.reasons
