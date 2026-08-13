"""source_session 审计链路单元测试 — 覆盖 bug 修复 6 层（A/B1/B2/C1/C2/D）。

修复对应 `documents/bug/` 描述：MCP 工具调用审计日志缺失"源系统会话标识"
（Oracle SID/SERIAL#、MySQL CONNECTION_ID、Linux SSH PID）。

分层覆盖：
- A:  context._build_request_summary 补 execution_id / env_code 分支（异步轮询场景）
- B1: database executor Oracle SID/SERIAL# + MySQL CONNECTION_ID 捕获
- B2: server executor 通过 `echo $$; exec` 包装捕获远端 shell PID
- C1: McpContext 新增 source_session 字段
- C2: log_mcp_call 将 source_session 合并入 extra_data 落审计
- D:  _get_execution_status / _get_server_execution_status 顶层返回 source_session
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _now_monotonic() -> float:
    """_execution_store TTL 使用 time.monotonic()，必须用同期钟设置 _created_at。
    使用 0 会被视为 'infinitely old'，被 _cleanup_expired_executions 立即清理。
    """
    return time.monotonic()

from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.mcp_server.context import (
    McpContext,
    _build_request_summary,
    build_context,
)
from platform_mcp.skills.database.executor import SQLExecutor
from platform_mcp.skills.server.executor import ServerExecutor
from platform_mcp.server.manager import ServerConnParams


# ============================================================
# Layer A: _build_request_summary 异步轮询分支
# ============================================================


class TestRequestSummaryAsyncBranches:
    """A: 异步状态轮询工具的 request_summary 分支。"""

    def test_get_execution_status_含_execution_id(self):
        summary = _build_request_summary(
            "get_execution_status", {"execution_id": "exec-abc-123"}
        )
        assert summary == "tool=get_execution_status execution_id=exec-abc-123"

    def test_get_server_execution_status_含_execution_id(self):
        summary = _build_request_summary(
            "get_server_execution_status", {"execution_id": "exec-xyz-789"}
        )
        assert summary == "tool=get_server_execution_status execution_id=exec-xyz-789"

    def test_list_datasources_仅_env_code(self):
        summary = _build_request_summary("list_datasources", {"env_code": "DEV"})
        assert summary == "tool=list_datasources env=DEV"

    def test_list_servers_仅_env_code(self):
        summary = _build_request_summary("list_servers", {"env_code": "UAT"})
        assert summary == "tool=list_servers env=UAT"

    def test_无参数_回退_tool_only(self):
        summary = _build_request_summary("list_datasources", {})
        assert summary == "tool=list_datasources"


# ============================================================
# Layer B1: database executor source_session 捕获
# ============================================================


def _oracle_params() -> ConnectionParams:
    return ConnectionParams(
        db_type="oracle", host="10.0.0.1", port=1521,
        username="u", password="p", datasource_code="ds1",
    )


def _mysql_params() -> ConnectionParams:
    return ConnectionParams(
        db_type="mysql", host="localhost", port=3306,
        username="root", password="", datasource_code="ds1",
    )


class TestOracleSourceSessionCapture:
    """B1-Oracle: 捕获 conn.session_id + conn.serial_num → source_session。"""

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_有结果集_捕获_sid_serial(self, mock_get_conn):
        executor = SQLExecutor()

        mock_cursor = MagicMock()
        mock_cursor.description = [("id",)]
        mock_cursor.rowcount = 1
        mock_cursor.fetchmany.return_value = [(1,)]
        mock_cursor.close = MagicMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.session_id = 12345
        mock_conn.serial_num = 678
        mock_conn.commit = MagicMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        async def run_sync(_loop, fn):
            return fn()

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = run_sync
            mock_get_loop.return_value = mock_loop

            result = await executor.execute_query(_oracle_params(), "SELECT id FROM t")

        assert result.success is True
        assert result.source_session == {
            "type": "oracle", "sid": 12345, "serial": 678,
        }

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_无_sid_返回_None(self, mock_get_conn):
        executor = SQLExecutor()

        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.rowcount = 0
        mock_cursor.close = MagicMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.session_id = None
        mock_conn.serial_num = None
        mock_conn.commit = MagicMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        async def run_sync(_loop, fn):
            return fn()

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = run_sync
            mock_get_loop.return_value = mock_loop

            result = await executor.execute_query(_oracle_params(), "DELETE FROM t")

        assert result.success is True
        assert result.source_session is None


class TestMysqlSourceSessionCapture:
    """B1-MySQL: 在主 SQL 之前执行 SELECT CONNECTION_ID() 捕获 conn_id。"""

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_捕获_conn_id(self, mock_get_conn):
        executor = SQLExecutor()

        mock_cursor = AsyncMock()
        mock_cursor.description = [("id",)]
        mock_cursor.rowcount = 1
        mock_cursor.fetchone = AsyncMock(return_value=(42,))
        mock_cursor.fetchmany = AsyncMock(return_value=[(1,)])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = AsyncMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        result = await executor.execute_query(_mysql_params(), "SELECT id FROM t")

        assert result.success is True
        assert result.source_session == {"type": "mysql", "conn_id": 42}
        # 验证 CONNECTION_ID() 在主 SQL 之前执行
        executed_sqls = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert "SELECT CONNECTION_ID()" in executed_sqls
        assert executed_sqls.index("SELECT CONNECTION_ID()") < executed_sqls.index("SELECT id FROM t")

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_connection_id查询失败_不阻断主流程(self, mock_get_conn):
        executor = SQLExecutor()

        mock_cursor = AsyncMock()
        mock_cursor.description = [("id",)]
        mock_cursor.rowcount = 1

        # 第一次 execute（CONNECTION_ID）抛异常，第二次（主 SQL）正常
        async def fake_execute(sql):
            if "CONNECTION_ID" in sql:
                raise RuntimeError("privilege denied")
            return None
        mock_cursor.execute = AsyncMock(side_effect=fake_execute)
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_cursor.fetchmany = AsyncMock(return_value=[(1,)])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = AsyncMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        result = await executor.execute_query(_mysql_params(), "SELECT id FROM t")

        assert result.success is True
        assert result.source_session is None  # 异常时安全回退


# ============================================================
# Layer B2: server executor 远端 shell PID 捕获
# ============================================================


def _server_params() -> ServerConnParams:
    return ServerConnParams(
        server_code="linux-app-dev", host="127.0.0.1", ssh_port=22,
        username="u", password="p", env_code="DEV",
        max_concurrent=3, command_timeout=60,
    )


class TestServerShellPidCapture:
    """B2: execute_command 通过 `echo $$; exec <cmd>` 包装捕获 PID。"""

    @pytest.mark.asyncio
    async def test_成功捕获_pid(self):
        executor = ServerExecutor()
        fake_result = MagicMock(
            exit_status=0,
            stdout="23456\nhello world\n",
            stderr="",
        )
        with patch("platform_mcp.skills.server.executor.ssh_connection") as mock_ssh:
            mock_conn = AsyncMock()
            mock_conn.run = AsyncMock(return_value=fake_result)
            mock_ssh.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ssh.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await executor.execute_command(_server_params(), "echo hello world")

        assert result.success is True
        assert result.source_session == {"type": "linux", "pid": 23456}
        # stdout 已剥离 PID 行
        assert result.stdout == "hello world\n"

    @pytest.mark.asyncio
    async def test_首行非数字_回退_None(self):
        executor = ServerExecutor()
        fake_result = MagicMock(
            exit_status=0,
            stdout="not-a-pid\nhello\n",
            stderr="",
        )
        with patch("platform_mcp.skills.server.executor.ssh_connection") as mock_ssh:
            mock_conn = AsyncMock()
            mock_conn.run = AsyncMock(return_value=fake_result)
            mock_ssh.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ssh.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await executor.execute_command(_server_params(), "echo hello")

        assert result.success is True
        assert result.source_session is None

    @pytest.mark.asyncio
    async def test_空输出_回退_None(self):
        executor = ServerExecutor()
        fake_result = MagicMock(exit_status=0, stdout="", stderr="")
        with patch("platform_mcp.skills.server.executor.ssh_connection") as mock_ssh:
            mock_conn = AsyncMock()
            mock_conn.run = AsyncMock(return_value=fake_result)
            mock_ssh.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ssh.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await executor.execute_command(_server_params(), "true")

        assert result.success is True
        assert result.source_session is None


# ============================================================
# Layer C1+C2: ctx.source_session → audit extra_data 序列化
# ============================================================


def _make_audit_context() -> McpContext:
    return McpContext(
        trace_id="t1",
        request_id="r1",
        operator="admin",
        skill_name="database",
        tool_name="execute_sql_text",
        target_datasource="ds1",
        target_env="DEV",
    )


class TestAuditExtraDataSerialization:
    """C1+C2: source_session 通过 ctx.source_session 合并入 extra_data 落审计。"""

    @pytest.mark.asyncio
    async def test_source_session_合入_extra_data(self):
        ctx = _make_audit_context()
        ctx.source_session = {"type": "oracle", "sid": 99, "serial": 1}
        ctx.extra_data = {"statement_type": "SELECT"}

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_sess_ctx = MagicMock()
        mock_sess_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sess_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory", return_value=mock_sess_ctx), \
             patch("platform_mcp.audit.logger.write_audit_log", new_callable=AsyncMock) as mock_write:
            from platform_mcp.mcp_server.call_log import log_mcp_call
            await log_mcp_call(ctx, "success", 80)
            kwargs = mock_write.call_args.kwargs

        merged = kwargs["extra_data"]
        assert merged["statement_type"] == "SELECT"
        assert merged["source_session"] == {"type": "oracle", "sid": 99, "serial": 1}

    @pytest.mark.asyncio
    async def test_source_session_None_不注入(self):
        ctx = _make_audit_context()
        ctx.source_session = None
        ctx.extra_data = {"row_count": 5}

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_sess_ctx = MagicMock()
        mock_sess_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sess_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory", return_value=mock_sess_ctx), \
             patch("platform_mcp.audit.logger.write_audit_log", new_callable=AsyncMock) as mock_write:
            from platform_mcp.mcp_server.call_log import log_mcp_call
            await log_mcp_call(ctx, "success", 30)
            kwargs = mock_write.call_args.kwargs

        # source_session None 时不应出现在 extra_data
        assert "source_session" not in (kwargs["extra_data"] or {})

    @pytest.mark.asyncio
    async def test_source_session_唯一字段_仅注入_source_session(self):
        ctx = _make_audit_context()
        ctx.source_session = {"type": "linux", "pid": 9999}
        ctx.extra_data = None  # 无其他扩展

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_sess_ctx = MagicMock()
        mock_sess_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sess_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("platform_mcp.common.database._ensure_engine"), \
             patch("platform_mcp.common.database.async_session_factory", return_value=mock_sess_ctx), \
             patch("platform_mcp.audit.logger.write_audit_log", new_callable=AsyncMock) as mock_write:
            from platform_mcp.mcp_server.call_log import log_mcp_call
            await log_mcp_call(ctx, "success", 12)
            kwargs = mock_write.call_args.kwargs

        assert kwargs["extra_data"] == {"source_session": {"type": "linux", "pid": 9999}}


# ============================================================
# Layer D: 异步状态查询顶层暴露 source_session
# ============================================================


class TestDatabaseGetExecutionStatusExposesSourceSession:
    """D-database: _get_execution_status 顶层返回 source_session。"""

    def test_异步完成_暴露_oracle_session(self):
        from platform_mcp.skills.database import DatabaseSkill, _execution_store

        _execution_store.clear()
        _execution_store["exec-1"] = {
            "status": "SUCCESS",
            "result": {
                "success": True,
                "source_session": {"type": "oracle", "sid": 123, "serial": 456},
            },
            "risk_level": "LOW",
            "_created_at": _now_monotonic(),
        }
        try:
            skill = DatabaseSkill()
            ret = skill._get_execution_status({"execution_id": "exec-1"})
            assert ret["success"] is True
            assert ret["source_session"] == {"type": "oracle", "sid": 123, "serial": 456}
        finally:
            _execution_store.clear()

    def test_异步完成_暴露_mysql_session(self):
        from platform_mcp.skills.database import DatabaseSkill, _execution_store

        _execution_store.clear()
        _execution_store["exec-2"] = {
            "status": "SUCCESS",
            "result": {
                "success": True,
                "source_session": {"type": "mysql", "conn_id": 888},
            },
            "risk_level": "LOW",
            "_created_at": _now_monotonic(),
        }
        try:
            skill = DatabaseSkill()
            ret = skill._get_execution_status({"execution_id": "exec-2"})
            assert ret["source_session"] == {"type": "mysql", "conn_id": 888}
        finally:
            _execution_store.clear()

    def test_结果为列表_取首个_有_session(self):
        """execute_sql_file 异步结果为 list[ExecutionResult]，取首个有 session 的。"""
        from platform_mcp.skills.database import DatabaseSkill, _execution_store

        _execution_store.clear()
        _execution_store["exec-3"] = {
            "status": "SUCCESS",
            "result": [
                {"success": True, "source_session": None},
                {"success": True, "source_session": {"type": "mysql", "conn_id": 7}},
            ],
            "risk_level": "LOW",
            "_created_at": _now_monotonic(),
        }
        try:
            skill = DatabaseSkill()
            ret = skill._get_execution_status({"execution_id": "exec-3"})
            assert ret["source_session"] == {"type": "mysql", "conn_id": 7}
        finally:
            _execution_store.clear()

    def test_无_session_返回_None(self):
        from platform_mcp.skills.database import DatabaseSkill, _execution_store

        _execution_store.clear()
        _execution_store["exec-4"] = {
            "status": "SUCCESS",
            "result": {"success": True},
            "risk_level": "LOW",
            "_created_at": _now_monotonic(),
        }
        try:
            skill = DatabaseSkill()
            ret = skill._get_execution_status({"execution_id": "exec-4"})
            assert ret["source_session"] is None
        finally:
            _execution_store.clear()

    def test_记录不存在(self):
        from platform_mcp.skills.database import DatabaseSkill, _execution_store

        _execution_store.clear()
        skill = DatabaseSkill()
        ret = skill._get_execution_status({"execution_id": "nonexistent"})
        assert ret["success"] is False


class TestServerGetExecutionStatusExposesSourceSession:
    """D-server: _get_server_execution_status 顶层返回 source_session。"""

    def test_暴露_linux_pid(self):
        from platform_mcp.skills.server import ServerSkill, _execution_store

        _execution_store.clear()
        _execution_store["srv-exec-1"] = {
            "status": "SUCCESS",
            "result": {
                "success": True,
                "source_session": {"type": "linux", "pid": 31415},
            },
            "risk_level": "LOW",
            "source_type": "command",
            "_created_at": _now_monotonic(),
        }
        try:
            skill = ServerSkill()
            ret = skill._get_server_execution_status({"execution_id": "srv-exec-1"})
            assert ret["success"] is True
            assert ret["source_session"] == {"type": "linux", "pid": 31415}
        finally:
            _execution_store.clear()

    def test_无_session_返回_None(self):
        from platform_mcp.skills.server import ServerSkill, _execution_store

        _execution_store.clear()
        _execution_store["srv-exec-2"] = {
            "status": "SUCCESS",
            "result": {"success": True},
            "risk_level": "LOW",
            "source_type": "command",
            "_created_at": _now_monotonic(),
        }
        try:
            skill = ServerSkill()
            ret = skill._get_server_execution_status({"execution_id": "srv-exec-2"})
            assert ret["source_session"] is None
        finally:
            _execution_store.clear()

    def test_记录不存在(self):
        from platform_mcp.skills.server import ServerSkill, _execution_store

        _execution_store.clear()
        skill = ServerSkill()
        ret = skill._get_server_execution_status({"execution_id": "no-such"})
        assert ret["success"] is False


# ============================================================
# Layer C1 字段定义验证
# ============================================================


class TestMcpContextSourceSessionField:
    """C1: McpContext dataclass 必须有 source_session 字段且默认 None。"""

    def test_字段存在_默认_None(self):
        ctx = McpContext(
            trace_id="t",
            request_id="r",
            operator="op",
            skill_name="database",
            tool_name="execute_sql_text",
        )
        assert hasattr(ctx, "source_session")
        assert ctx.source_session is None

    def test_字段可赋值(self):
        ctx = McpContext(
            trace_id="t",
            request_id="r",
            operator="op",
            skill_name="database",
            tool_name="execute_sql_text",
        )
        ctx.source_session = {"type": "oracle", "sid": 1, "serial": 2}
        assert ctx.source_session["sid"] == 1


# ============================================================
# 端到端 build_context 不影响 source_session 字段
# ============================================================


class TestBuildContextSourceSessionNeutral:
    """build_context 不设置 source_session（由 _handler 后续填充）。"""

    def test_build_context_不预设_source_session(self):
        ctx = build_context("execute_sql_text", datasource_code="ds1", env_code="DEV")
        assert ctx.source_session is None
