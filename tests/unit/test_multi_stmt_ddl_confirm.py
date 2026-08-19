"""多语句 DDL 整批 confirm（方案B）+ SQL*Plus `/` 语句终结符 — 用例

契约：
- 行首独立 `/` 是语句终结符（无尾分号的 DDL / PLSQL 块依赖它），分句前归一为 `;`
- 多语句含 HIGH/CRITICAL：DEV/UAT 返回 CONFIRM_REQUIRED + 逐语句风险清单，
  confirm_token 绑定全部语句拼接内容的 hash；携 token 重调后整批执行
- PROD 维持 MULTI_STMT_HIGH_RISK 直接拒绝
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.skills.common.risk_types import RiskLevel
from platform_mcp.skills.database import DatabaseSkill


@dataclass
class FakeRiskResult:
    level: RiskLevel
    reasons: list[str]
    statement_type: str
    needs_confirm: bool


def _make_risk(level_value: str, needs_confirm: bool = False, statement_type: str = "SELECT"):
    return FakeRiskResult(
        level=RiskLevel(level_value), reasons=["test"],
        statement_type=statement_type, needs_confirm=needs_confirm,
    )


@dataclass
class FakeExecResult:
    success: bool = True
    rows: list | None = None
    columns: list | None = None
    row_count: int = 0
    error_message: str | None = None


# ---------- ① `/` 语句终结符 ----------

def test_斜杠作为无分号DDL的语句终结符():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements("CREATE TABLE a (id INT)\n/\nCREATE TABLE b (id INT)\n/")
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE TABLE a")
    assert stmts[1].startswith("CREATE TABLE b")


def test_无尾分号PLSQL块不被切碎():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements(
        "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END\n/\nCREATE TABLE b (id INT)\n/"
    )
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE OR REPLACE PROCEDURE")
    assert "END" in stmts[0]  # 块尾完整（含内部 NULL; 分号未被切碎）
    assert stmts[1].startswith("CREATE TABLE b")


def test_分号后跟斜杠不产生空语句():
    from platform_mcp.skills.database.executor import split_statements

    assert split_statements("DROP TABLE t;\n/\nSELECT 1 FROM DUAL;\n/") == [
        "DROP TABLE t", "SELECT 1 FROM DUAL",
    ]


# ---------- ③ 匿名/命名 PL/SQL 块不拆碎 ----------

def test_匿名PLSQL块整块不拆碎():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements("BEGIN\n  NULL;\n  NULL;\nEND;\n/")
    assert len(stmts) == 1
    assert stmts[0].startswith("BEGIN")
    assert "NULL;" in stmts[0]
    # 块语句的 END; 分号是块语法一部分，必须保留（PLS-00103 否则报 end-of-file 等 ;）
    assert stmts[0].rstrip().endswith("END;")


def test_DECLARE开头的块整块不拆碎():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements("DECLARE\n  x NUMBER;\nBEGIN\n  x := 1;\nEND;\n/")
    assert len(stmts) == 1
    assert stmts[0].startswith("DECLARE")
    assert stmts[0].rstrip().endswith("END;")


def test_块内嵌套与END_IF_LOOP不误判层级():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements(
        "BEGIN\n"
        "  IF 1=1 THEN NULL; END IF;\n"
        "  FOR r IN (SELECT 1 FROM DUAL) LOOP NULL; END LOOP;\n"
        "  BEGIN NULL; END;\n"
        "END;\n/"
    )
    assert len(stmts) == 1
    assert stmts[0].count("END IF;") == 1
    assert stmts[0].count("END LOOP;") == 1


def test_混合脚本_普通语句与块各自独立():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements(
        "INSERT INTO a VALUES (1);\n"
        "BEGIN\n  NULL;\nEND;\n"
        "/\n"
        "INSERT INTO b VALUES (2);\n"
    )
    assert len(stmts) == 3
    assert stmts[0] == "INSERT INTO a VALUES (1)"
    assert stmts[1].startswith("BEGIN")
    assert stmts[2] == "INSERT INTO b VALUES (2)"


def test_块内字符串字面量中的分号不受影响():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements("BEGIN\n  s := 'a;b';\nEND;\n/")
    assert len(stmts) == 1
    assert "'a;b'" in stmts[0]


def test_块语句保留END分号而普通语句剥离尾分号():
    from platform_mcp.skills.database.executor import split_statements

    stmts = split_statements("BEGIN\n  NULL;\nEND;\n/\nSELECT 1 FROM DUAL;\n")
    assert stmts == ["BEGIN\n  NULL;\nEND;", "SELECT 1 FROM DUAL"]


# ---------- ② 整批 confirm ----------

_SQL_BATCH = "CREATE TABLE a (id INT);\nDROP TABLE b;"


@pytest.mark.asyncio
async def test_多语句含高风险_DEV返回整批confirm清单():
    skill = DatabaseSkill()
    with patch("platform_mcp.skills.database.risk_engine.analyze",
               return_value=_make_risk("HIGH", needs_confirm=True, statement_type="CREATE")), \
         patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se:
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se.execute_statements = AsyncMock()
        result = await skill._execute_sql_text(
            {"sql_text": _SQL_BATCH, "datasource_code": "ds1"}, None
        )
        assert result["success"] is False
        assert result["error_code"] == "CONFIRM_REQUIRED"
        assert result["statement_count"] == 2
        assert result["risk_level"] == "HIGH"
        assert [m["index"] for m in result["high_risk_statements"]] == [1, 2]
        assert all(m["risk_level"] == "HIGH" for m in result["high_risk_statements"])
        assert result["confirm_token"]
        mock_se.execute_statements.assert_not_awaited()


@pytest.mark.asyncio
async def test_多语句confirm重试_整批执行():
    skill = DatabaseSkill()
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se:
        mock_re.analyze.return_value = _make_risk("HIGH", needs_confirm=True, statement_type="CREATE")
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se.execute_statements = AsyncMock(return_value=[FakeExecResult(success=True)] * 2)

        first = await skill._execute_sql_text(
            {"sql_text": _SQL_BATCH, "datasource_code": "ds1"}, None
        )
        assert first["error_code"] == "CONFIRM_REQUIRED"

        second = await skill._execute_sql_text(
            {"sql_text": _SQL_BATCH, "datasource_code": "ds1", "confirm_token": first["confirm_token"]},
            None,
        )
        assert second["success"] is True
        mock_se.execute_statements.assert_awaited_once()
        assert len(mock_se.execute_statements.await_args.args[0]) == 2


@pytest.mark.asyncio
async def test_多语句token绑定整批内容_篡改后失效():
    skill = DatabaseSkill()
    with patch("platform_mcp.skills.database.risk_engine.analyze",
               return_value=_make_risk("HIGH", needs_confirm=True, statement_type="CREATE")), \
         patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se:
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se.execute_statements = AsyncMock()

        first = await skill._execute_sql_text(
            {"sql_text": _SQL_BATCH, "datasource_code": "ds1"}, None
        )
        result = await skill._execute_sql_text(
            {
                "sql_text": "CREATE TABLE a (id INT);\nDROP TABLE c;",  # 内容被篡改
                "datasource_code": "ds1",
                "confirm_token": first["confirm_token"],
            },
            None,
        )
        assert result["success"] is False
        assert result["error_code"] == "CONFIRM_TOKEN_INVALID"
        mock_se.execute_statements.assert_not_awaited()


@pytest.mark.asyncio
async def test_多语句高风险_PROD维持直接拒绝():
    skill = DatabaseSkill()
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm:
        mock_re.analyze.return_value = _make_risk("HIGH", needs_confirm=True, statement_type="CREATE")
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        result = await skill._execute_sql_text(
            {"sql_text": _SQL_BATCH, "datasource_code": "ds1", "env_code": "PROD"}, None
        )
        assert result["success"] is False
        assert result["error_code"] == "MULTI_STMT_HIGH_RISK"
        assert "拆分为单语句" in result["message"]
