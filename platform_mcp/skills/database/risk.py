"""SQL 风险识别引擎 — sqlparse + 正则 + 关键词（架构 §11）"""

from __future__ import annotations

import re

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import DDL, DML, Keyword

from platform_mcp.skills.common.risk_types import RiskLevel, RiskResult, _LEVEL_ORDER


_CRITICAL_KEYWORDS = re.compile(r"\b(DROP|TRUNCATE)\b", re.IGNORECASE | re.MULTILINE)
_HIGH_KEYWORDS = re.compile(r"\b(CALL|EXEC|EXECUTE)\s+", re.IGNORECASE | re.MULTILINE)
_DML_TYPES = {"SELECT", "INSERT", "UPDATE", "DELETE"}
_DDL_TYPES = {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME"}


class RiskEngine:

    def analyze(self, sql: str, env_code: str = "DEV") -> RiskResult:
        sql_stripped = sql.strip()
        if not sql_stripped:
            return RiskResult(level=RiskLevel.LOW, statement_type="EMPTY")

        parsed = sqlparse.parse(sql_stripped)
        if not parsed:
            return RiskResult(
                level=RiskLevel.HIGH,
                reasons=["SQL 解析失败"],
                statement_type="UNKNOWN",
            )

        stmt = parsed[0]
        stmt_type = self._classify_statement(stmt)
        reasons: list[str] = []
        level = self._assess_risk(stmt, sql_stripped, stmt_type, reasons)

        if env_code == "PROD":
            if stmt_type in _DDL_TYPES and _LEVEL_ORDER[level] < _LEVEL_ORDER[RiskLevel.CRITICAL]:
                level = RiskLevel.CRITICAL
                reasons.append("生产库 DDL 操作强制 CRITICAL")
            if self._is_dml_without_where(sql_stripped) and _LEVEL_ORDER[level] < _LEVEL_ORDER[RiskLevel.CRITICAL]:
                level = RiskLevel.CRITICAL
                reasons.append("生产库无 WHERE 的 DELETE/UPDATE 强制 CRITICAL")

        return RiskResult(level=level, reasons=reasons, statement_type=stmt_type)

    def _classify_statement(self, stmt: Statement) -> str:
        first_token = stmt.token_first(skip_ws=True, skip_cm=True)
        if first_token and first_token.ttype in (DML, DDL, Keyword):
            return str(first_token.normalized).upper()
        val = str(first_token.normalized).upper() if first_token else ""
        return val if val in _DDL_TYPES | _DML_TYPES else "UNKNOWN"

    def _assess_risk(self, stmt: Statement, sql: str, stmt_type: str, reasons: list[str]) -> RiskLevel:
        critical_match = _CRITICAL_KEYWORDS.search(sql)
        if critical_match:
            kw = critical_match.group(1).upper()
            reasons.append(f"高危操作: {kw}")
            return RiskLevel.CRITICAL

        if stmt_type in ("CREATE", "ALTER", "RENAME"):
            reasons.append(f"DDL 操作: {stmt_type}")
            return RiskLevel.HIGH

        if self._is_dml_without_where(sql):
            reasons.append("DELETE/UPDATE 无 WHERE 子句")
            return RiskLevel.HIGH

        if _HIGH_KEYWORDS.search(sql):
            reasons.append("存储过程调用")
            return RiskLevel.HIGH

        if stmt_type == "UNKNOWN":
            reasons.append("SQL 语句类型无法识别")
            return RiskLevel.HIGH

        if stmt_type in ("INSERT", "UPDATE", "DELETE"):
            return RiskLevel.MEDIUM

        return RiskLevel.LOW

    def _is_dml_without_where(self, sql: str) -> bool:
        upper = sql.upper().strip()
        if upper.startswith("DELETE") and "WHERE" not in upper:
            return True
        if upper.startswith("UPDATE") and "WHERE" not in upper:
            return True
        return False


risk_engine = RiskEngine()
