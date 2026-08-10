"""Database Skill 单元测试 — validate/execute/tool 实现"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.skills.database import DatabaseSkill


@dataclass
class FakeRiskResult:
    level: MagicMock
    reasons: list[str]
    statement_type: str
    needs_confirm: bool


def _make_risk(level_value: str, needs_confirm: bool = False, statement_type: str = "SELECT"):
    lvl = MagicMock()
    lvl.value = level_value
    return FakeRiskResult(level=lvl, reasons=["test"], statement_type=statement_type, needs_confirm=needs_confirm)


@dataclass
class FakeExecResult:
    success: bool = True
    rows: list | None = None
    columns: list | None = None
    row_count: int = 0
    error_message: str | None = None


# --- list_tools ---

def test_list_tools_返回5个ToolMeta():
    skill = DatabaseSkill()
    tools = skill.list_tools()
    assert len(tools) == 5
    names = {t.tool_name for t in tools}
    assert names == {"execute_sql_text", "execute_sql_file", "validate_sql", "list_datasources", "get_execution_status"}


def test_skill_name_返回database():
    assert DatabaseSkill().skill_name() == "database"


def test_support_已知工具返回True():
    assert DatabaseSkill().support("execute_sql_text") is True


def test_support_未知工具返回False():
    assert DatabaseSkill().support("unknown_tool") is False


# --- validate ---

@pytest.mark.asyncio
async def test_validate_execute_sql_text_缺少datasource_code():
    from platform_mcp.common.exceptions import SkillError
    with pytest.raises(SkillError, match="datasource_code"):
        await DatabaseSkill().validate("execute_sql_text", {"sql_text": "SELECT 1"})


@pytest.mark.asyncio
async def test_validate_execute_sql_text_缺少sql_text():
    from platform_mcp.common.exceptions import SkillError
    with pytest.raises(SkillError, match="sql_text"):
        await DatabaseSkill().validate("execute_sql_text", {"datasource_code": "ds1"})


@pytest.mark.asyncio
async def test_validate_execute_sql_file_缺少file_path():
    from platform_mcp.common.exceptions import SkillError
    with pytest.raises(SkillError, match="file_path"):
        await DatabaseSkill().validate("execute_sql_file", {"datasource_code": "ds1"})


@pytest.mark.asyncio
async def test_validate_execute_sql_file_缺少datasource_code():
    from platform_mcp.common.exceptions import SkillError
    with pytest.raises(SkillError, match="datasource_code"):
        await DatabaseSkill().validate("execute_sql_file", {"file_path": "/tmp/a.sql"})


@pytest.mark.asyncio
async def test_validate_list_datasources_无必填参数():
    result = await DatabaseSkill().validate("list_datasources", {})
    assert result == {}


@pytest.mark.asyncio
async def test_validate_get_status_缺少execution_id():
    from platform_mcp.common.exceptions import SkillError
    with pytest.raises(SkillError, match="execution_id"):
        await DatabaseSkill().validate("get_execution_status", {})


@pytest.mark.asyncio
async def test_validate_execute_sql_text_参数齐全_返回原参数():
    params = {"datasource_code": "ds1", "sql_text": "SELECT 1"}
    result = await DatabaseSkill().validate("execute_sql_text", params)
    assert result == params


# --- execute 路由 ---

@pytest.mark.asyncio
async def test_execute_路由到_execute_sql_text():
    skill = DatabaseSkill()
    with patch.object(skill, "_execute_sql_text", new_callable=AsyncMock, return_value={"ok": True}) as m:
        result = await skill.execute("execute_sql_text", {"sql_text": "SELECT 1", "datasource_code": "ds1"}, None)
        assert result == {"ok": True}
        m.assert_called_once()


@pytest.mark.asyncio
async def test_execute_路由到_execute_sql_file():
    skill = DatabaseSkill()
    with patch.object(skill, "_execute_sql_file", new_callable=AsyncMock, return_value={"ok": True}):
        result = await skill.execute("execute_sql_file", {"file_path": "/a.sql", "datasource_code": "ds1"}, None)
        assert result == {"ok": True}


@pytest.mark.asyncio
async def test_execute_路由到_validate_sql():
    skill = DatabaseSkill()
    with patch.object(skill, "_validate_sql", new_callable=AsyncMock, return_value={"risk": "LOW"}):
        result = await skill.execute("validate_sql", {"sql_text": "SELECT 1"}, None)
        assert result == {"risk": "LOW"}


@pytest.mark.asyncio
async def test_execute_路由到_list_datasources():
    skill = DatabaseSkill()
    with patch.object(skill, "_list_datasources", new_callable=AsyncMock, return_value={"total": 0}):
        result = await skill.execute("list_datasources", {}, None)
        assert result == {"total": 0}


@pytest.mark.asyncio
async def test_execute_路由到_get_execution_status():
    skill = DatabaseSkill()
    with patch.object(skill, "_get_execution_status", return_value={"success": True}):
        result = await skill.execute("get_execution_status", {"execution_id": "abc"}, None)
        assert result == {"success": True}


@pytest.mark.asyncio
async def test_execute_未知工具_NotImplementedError():
    with pytest.raises(NotImplementedError, match="unknown"):
        await DatabaseSkill().execute("unknown", {}, None)


# --- _execute_sql_text ---

@pytest.mark.asyncio
async def test_execute_sql_text_低风险直接执行():
    skill = DatabaseSkill()
    risk = _make_risk("LOW", needs_confirm=False)
    fake_result = FakeExecResult(success=True, rows=[], columns=["id"], row_count=0)
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se:
        mock_re.analyze.return_value = risk
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se.execute_query = AsyncMock(return_value=fake_result)
        result = await skill._execute_sql_text(
            {"sql_text": "SELECT 1", "datasource_code": "ds1"}, None
        )
        assert result["success"] is True
        assert result["risk_level"] == "LOW"


@pytest.mark.asyncio
async def test_execute_sql_text_高风险无token_返回confirm信息():
    skill = DatabaseSkill()
    risk = _make_risk("HIGH", needs_confirm=True)
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.skills.database.confirm.confirm_manager") as mock_cm:
        mock_re.analyze.return_value = risk
        mock_cm.generate.return_value = "tok_123"
        result = await skill._execute_sql_text(
            {"sql_text": "DELETE FROM t", "datasource_code": "ds1"}, None
        )
        assert result["success"] is False
        assert result["confirm_token"] == "tok_123"
        assert "需要二次确认" in result["message"]


@pytest.mark.asyncio
async def test_execute_sql_text_高风险有效token_执行成功():
    skill = DatabaseSkill()
    risk = _make_risk("HIGH", needs_confirm=True)
    fake_result = FakeExecResult(success=True, rows=[], columns=[], row_count=0)
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.skills.database.confirm.confirm_manager") as mock_cm, \
         patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se:
        mock_re.analyze.return_value = risk
        mock_cm.validate.return_value = {"valid": True}
        mock_cm.consume = MagicMock()
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se.execute_query = AsyncMock(return_value=fake_result)
        result = await skill._execute_sql_text(
            {"sql_text": "DELETE FROM t", "datasource_code": "ds1", "confirm_token": "tok_123"}, None
        )
        assert result["success"] is True
        mock_cm.consume.assert_called_once_with("tok_123")


@pytest.mark.asyncio
async def test_execute_sql_text_高风险无效token_返回错误():
    skill = DatabaseSkill()
    risk = _make_risk("HIGH", needs_confirm=True)
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.skills.database.confirm.confirm_manager") as mock_cm:
        mock_re.analyze.return_value = risk
        mock_cm.validate.return_value = None
        result = await skill._execute_sql_text(
            {"sql_text": "DELETE FROM t", "datasource_code": "ds1", "confirm_token": "bad"}, None
        )
        assert result["success"] is False
        assert "无效或已过期" in result["message"]


# --- _execute_sql_file ---

@pytest.mark.asyncio
async def test_execute_sql_file_正常执行():
    skill = DatabaseSkill()
    risk = _make_risk("LOW", needs_confirm=False)
    fake_path = MagicMock()
    fake_path.read_text.return_value = "SELECT 1;"
    fake_result = FakeExecResult(success=True)
    with patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se, \
         patch("platform_mcp.skills.database.risk.risk_engine") as mock_re:
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se._validate_file_path.return_value = fake_path
        mock_se.execute_file = AsyncMock(return_value=[fake_result])
        mock_re.analyze.return_value = risk
        result = await skill._execute_sql_file(
            {"file_path": "/a.sql", "datasource_code": "ds1"}, None
        )
        assert result["success"] is True
        assert result["statement_count"] == 1


@pytest.mark.asyncio
async def test_execute_sql_file_空文件报错():
    skill = DatabaseSkill()
    fake_path = MagicMock()
    fake_path.read_text.return_value = ""
    with patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se:
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se._validate_file_path.return_value = fake_path
        result = await skill._execute_sql_file(
            {"file_path": "/empty.sql", "datasource_code": "ds1"}, None
        )
        assert result["success"] is False
        assert "SQL 文件为空" in result["error_message"]


@pytest.mark.asyncio
async def test_execute_sql_file_高风险需confirm():
    skill = DatabaseSkill()
    risk = _make_risk("HIGH", needs_confirm=True)
    fake_path = MagicMock()
    fake_path.read_text.return_value = "DELETE FROM t;"
    with patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm, \
         patch("platform_mcp.skills.database.executor.sql_executor") as mock_se, \
         patch("platform_mcp.skills.database.risk.risk_engine") as mock_re, \
         patch("platform_mcp.skills.database.confirm.confirm_manager") as mock_cm:
        mock_dm.resolve_connection_params = AsyncMock(return_value=MagicMock())
        mock_se._validate_file_path.return_value = fake_path
        mock_re.analyze.return_value = risk
        mock_cm.generate.return_value = "tok_file"
        result = await skill._execute_sql_file(
            {"file_path": "/del.sql", "datasource_code": "ds1"}, None
        )
        assert result["success"] is False
        assert result["confirm_token"] == "tok_file"


# --- _validate_sql ---

@pytest.mark.asyncio
async def test_validate_sql_返回风险信息():
    skill = DatabaseSkill()
    risk = _make_risk("CRITICAL", needs_confirm=True, statement_type="DROP")
    with patch("platform_mcp.skills.database.risk.risk_engine") as mock_re:
        mock_re.analyze.return_value = risk
        result = await skill._validate_sql({"sql_text": "DROP TABLE t"})
        assert result["risk_level"] == "CRITICAL"
        assert result["needs_confirm"] is True
        assert result["statement_type"] == "DROP"


# --- _list_datasources ---

@pytest.mark.asyncio
async def test_list_datasources_返回列表():
    skill = DatabaseSkill()
    with patch("platform_mcp.datasource.manager.datasource_manager") as mock_dm:
        mock_dm.list_accessible_datasources = AsyncMock(
            return_value=[{"datasource_code": "ds1", "db_type": "oracle"}]
        )
        result = await skill._list_datasources({})
        assert result["total"] == 1
        assert result["datasources"][0]["datasource_code"] == "ds1"


# --- _get_execution_status ---

def test_get_execution_status_有记录():
    import platform_mcp.skills.database as mod
    mod._execution_store["exec_1"] = {"status": "SUCCESS", "result": None, "risk_level": "LOW", "_created_at": __import__("time").monotonic()}
    try:
        skill = DatabaseSkill()
        result = skill._get_execution_status({"execution_id": "exec_1"})
        assert result["success"] is True
    finally:
        mod._execution_store.pop("exec_1", None)


def test_get_execution_status_无记录():
    skill = DatabaseSkill()
    result = skill._get_execution_status({"execution_id": "nonexist"})
    assert result["success"] is False
    assert "不存在" in result["message"]


# ============================================================
# P0-4 第二轮补齐：覆盖 skills/database/__init__.py 缺失分支
# 目标行：L162, L201-203, L250-252, L266-268, L283-286, L289, L325, L331-336
# ============================================================


@pytest.mark.asyncio
async def test_validate_execute_sql_text_validate_sql_缺_sql_text():
    """L161-162: validate_sql 必填 sql_text"""
    skill = DatabaseSkill()
    with pytest.raises(Exception) as exc_info:
        await skill.validate("validate_sql", {})
    assert "sql_text" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_sql_text_get_current_identity_异常_不阻断():
    """L201-203: get_current_identity 抛异常时，role_code 仍为 None 不阻断"""
    skill = DatabaseSkill()
    with patch("platform_mcp.skills.database.executor.sql_executor.execute_query", new_callable=AsyncMock) as mock_exec, \
         patch("platform_mcp.datasource.manager.datasource_manager.resolve_connection_params", new_callable=AsyncMock), \
         patch("platform_mcp.skills.database.risk_engine.analyze", return_value=_make_risk("LOW")), \
         patch("platform_mcp.mcp_server.get_current_identity", side_effect=RuntimeError("var not set")):
        mock_exec.return_value = FakeExecResult(success=True)
        result = await skill.execute("execute_sql_text", {
            "sql_text": "SELECT 1",
            "datasource_code": "ds1",
            "env_code": "DEV",
        }, None)
        assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_sql_file_get_current_identity_异常_不阻断():
    """L250-252: _execute_sql_file 中 get_current_identity 异常分支"""
    import tempfile
    import os

    skill = DatabaseSkill()
    fd, path = tempfile.mkstemp(suffix=".sql")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("SELECT 1;")
        with patch("platform_mcp.skills.database.executor.sql_executor.execute_file", new_callable=AsyncMock) as mock_exec, \
             patch("platform_mcp.datasource.manager.datasource_manager.resolve_connection_params", new_callable=AsyncMock), \
             patch("platform_mcp.skills.database.risk_engine.analyze", return_value=_make_risk("LOW")), \
             patch("platform_mcp.mcp_server.get_current_identity", side_effect=RuntimeError("var not set")):
            mock_exec.return_value = [FakeExecResult(success=True)]
            result = await skill.execute("execute_sql_file", {
                "file_path": path,
                "datasource_code": "ds1",
                "env_code": "DEV",
            }, None)
            assert result["success"] is True
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_execute_sql_file_多语句风险升级():
    """L266-268: 多语句文件中，第二条语句风险更高时，max_risk 升级"""
    import tempfile
    import os
    from platform_mcp.skills.database.risk import RiskLevel

    skill = DatabaseSkill()
    fd, path = tempfile.mkstemp(suffix=".sql")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("SELECT 1; DROP TABLE users;")
        low_risk = _make_risk("LOW")
        low_risk.level = RiskLevel.LOW
        high_risk = _make_risk("HIGH", needs_confirm=True, statement_type="DROP")
        high_risk.level = RiskLevel.HIGH
        risk_results = iter([low_risk, high_risk])
        with patch("platform_mcp.skills.database.risk_engine.analyze", side_effect=lambda *a, **k: next(risk_results)), \
             patch("platform_mcp.datasource.manager.datasource_manager.resolve_connection_params", new_callable=AsyncMock):
            result = await skill.execute("execute_sql_file", {
                "file_path": path,
                "datasource_code": "ds1",
                "env_code": "DEV",
            }, None)
            assert result["success"] is False
            assert result["risk_level"] == "HIGH"
            assert "confirm_token" in result
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_execute_sql_file_high风险_invalid_confirm_token():
    """L283-286: sql_file HIGH 风险 + confirm_token 无效"""
    import tempfile
    import os

    skill = DatabaseSkill()
    fd, path = tempfile.mkstemp(suffix=".sql")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("DROP TABLE users;")
        with patch("platform_mcp.skills.database.risk_engine.analyze",
                   return_value=_make_risk("HIGH", needs_confirm=True, statement_type="DROP")), \
             patch("platform_mcp.datasource.manager.datasource_manager.resolve_connection_params", new_callable=AsyncMock), \
             patch("platform_mcp.skills.database.confirm.confirm_manager.validate", return_value=None):
            result = await skill.execute("execute_sql_file", {
                "file_path": path,
                "datasource_code": "ds1",
                "env_code": "DEV",
                "confirm_token": "invalid_token",
            }, None)
            assert result["success"] is False
            assert "confirm_token 无效" in result["message"]
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_execute_sql_file_async_exec():
    """L289, L325, L331-336: sql_file + async_exec → 异步提交 + file_path 存储"""
    import tempfile
    import os

    skill = DatabaseSkill()
    fd, path = tempfile.mkstemp(suffix=".sql")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("SELECT 1;")
        with patch("platform_mcp.skills.database.executor.sql_executor.execute_file", new_callable=AsyncMock) as mock_exec, \
             patch("platform_mcp.datasource.manager.datasource_manager.resolve_connection_params", new_callable=AsyncMock), \
             patch("platform_mcp.skills.database.risk_engine.analyze", return_value=_make_risk("LOW")):
            mock_exec.return_value = [FakeExecResult(success=True)]
            result = await skill.execute("execute_sql_file", {
                "file_path": path,
                "datasource_code": "ds1",
                "env_code": "DEV",
                "async_exec": True,
            }, None)
            assert result["success"] is True
            assert "execution_id" in result
            assert result["status"] == "PENDING"
            import asyncio
            await asyncio.sleep(0.05)
            import platform_mcp.skills.database as mod
            record = mod._execution_store.get(result["execution_id"])
            assert record is not None
            assert record.get("file_path") == path
            mod._execution_store.pop(result["execution_id"], None)
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_start_async_execution_异常路径():
    """L341-343: _run_background 异常时设置 status=ERROR"""
    skill = DatabaseSkill()
    with patch("platform_mcp.datasource.manager.datasource_manager.resolve_connection_params", new_callable=AsyncMock), \
         patch("platform_mcp.skills.database.risk_engine.analyze", return_value=_make_risk("LOW")), \
         patch("platform_mcp.skills.database.executor.sql_executor.execute_query",
               new_callable=AsyncMock, side_effect=RuntimeError("connection lost")):
        result = await skill.execute("execute_sql_text", {
            "sql_text": "SELECT 1",
            "datasource_code": "ds1",
            "env_code": "DEV",
            "async_exec": True,
        }, None)
        assert result["success"] is True
        assert result["status"] == "PENDING"
        import asyncio
        await asyncio.sleep(0.05)
        import platform_mcp.skills.database as mod
        record = mod._execution_store.get(result["execution_id"])
        assert record is not None
        assert record["status"] == "ERROR"
        assert "connection lost" in record["result"]["error_message"]
        mod._execution_store.pop(result["execution_id"], None)

