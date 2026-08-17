"""5.1.5 ConfirmTokenManager 单元测试 — 一次性 token 生成/验证/消费"""

import time
from unittest.mock import patch

from platform_mcp.skills.database.confirm import ConfirmTokenManager, ConfirmContext
from platform_mcp.skills.database.risk import RiskLevel


class TestConfirmTokenManager:
    def setup_method(self):
        self.manager = ConfirmTokenManager()

    def test_generate_returns_token_string(self):
        token = self.manager.generate("execute_sql_text", "test_ds", "SELECT 1", RiskLevel.LOW)
        assert isinstance(token, str)
        assert len(token) > 10

    def test_validate_correct_params_returns_context(self):
        token = self.manager.generate("execute_sql_text", "test_ds", "SELECT 1", RiskLevel.HIGH)
        ctx = self.manager.validate(token, "execute_sql_text", "test_ds")
        assert ctx is not None
        assert ctx.tool_name == "execute_sql_text"
        assert ctx.datasource_code == "test_ds"
        assert ctx.risk_level == RiskLevel.HIGH

    def test_validate_wrong_tool_name_returns_none(self):
        token = self.manager.generate("execute_sql_text", "test_ds", "SELECT 1", RiskLevel.HIGH)
        assert self.manager.validate(token, "execute_sql_file", "test_ds") is None

    def test_validate_wrong_datasource_returns_none(self):
        token = self.manager.generate("execute_sql_text", "test_ds", "SELECT 1", RiskLevel.HIGH)
        assert self.manager.validate(token, "execute_sql_text", "other_ds") is None

    def test_validate_unknown_token_returns_none(self):
        assert self.manager.validate("nonexistent", "execute_sql_text", "ds") is None

    def test_consume_removes_token(self):
        token = self.manager.generate("execute_sql_text", "ds", "SQL", RiskLevel.HIGH)
        self.manager.consume(token)
        assert self.manager.validate(token, "execute_sql_text", "ds") is None

    def test_consume_nonexistent_token_no_error(self):
        self.manager.consume("nonexistent")

    def test_token_expired_returns_none(self):
        token = self.manager.generate("execute_sql_text", "ds", "SQL", RiskLevel.HIGH)
        with patch("platform_mcp.skills.database.confirm.time.monotonic", return_value=time.monotonic() + 600):
            ctx = self.manager.validate(token, "execute_sql_text", "ds")
        assert ctx is None

    def test_cleanup_expired_tokens(self):
        self.manager.generate("t1", "ds", "SQL1", RiskLevel.HIGH)
        self.manager.generate("t2", "ds", "SQL2", RiskLevel.HIGH)
        assert len(self.manager._tokens) == 2
        with patch("platform_mcp.skills.database.confirm.time.monotonic", return_value=time.monotonic() + 600):
            self.manager._cleanup_expired()
        assert len(self.manager._tokens) == 0

    def test_sql_hash_consistency(self):
        token = self.manager.generate("t", "ds", "SELECT 1", RiskLevel.LOW)
        ctx = self.manager.validate(token, "t", "ds")
        assert ctx is not None
        assert len(ctx.sql_hash) == 16

    # --- BUG20260817 BUG-2 加固：validate 校验 sql_hash，封死"token 换 SQL"复用面 ---

    def test_validate_sql_hash匹配_返回ctx(self):
        token = self.manager.generate("execute_sql_text", "ds", "DROP TABLE t", RiskLevel.HIGH)
        ctx = self.manager.validate(
            token, "execute_sql_text", "ds",
            sql_hash=self.manager.hash_sql("DROP TABLE t"),
        )
        assert ctx is not None

    def test_validate_sql_hash不匹配_返回none(self):
        token = self.manager.generate("execute_sql_text", "ds", "DROP TABLE t", RiskLevel.HIGH)
        ctx = self.manager.validate(
            token, "execute_sql_text", "ds",
            sql_hash=self.manager.hash_sql("DROP TABLE other"),
        )
        assert ctx is None

    def test_validate_未传hash_不比对_向后兼容(self):
        token = self.manager.generate("execute_sql_text", "ds", "DROP TABLE t", RiskLevel.HIGH)
        assert self.manager.validate(token, "execute_sql_text", "ds") is not None

    def test_hash_sql_为sha256前16位(self):
        import hashlib
        assert self.manager.hash_sql("SELECT 1") == hashlib.sha256(b"SELECT 1").hexdigest()[:16]
