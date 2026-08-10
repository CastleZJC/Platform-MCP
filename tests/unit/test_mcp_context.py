"""McpContext 单元测试 — build_context / _infer_skill_name"""

from unittest.mock import patch

import pytest

from platform_mcp.mcp_server.context import (
    McpContext,
    _build_request_summary,
    build_context,
    _infer_skill_name,
)


class TestBuildContext:
    def test_build_context_database_tool(self):
        ctx = build_context("execute_sql_text", datasource_code="ds1", env_code="DEV")
        assert ctx.tool_name == "execute_sql_text"
        assert ctx.skill_name == "database"
        assert ctx.target_datasource == "ds1"
        assert ctx.target_env == "DEV"
        assert ctx.operator.startswith("mcp://")
        assert len(ctx.trace_id) > 0
        assert len(ctx.request_id) > 0

    def test_build_context_unknown_tool(self):
        ctx = build_context("some_unknown_tool")
        assert ctx.skill_name == "unknown"

    def test_trace_id_unique(self):
        ctx1 = build_context("t1")
        ctx2 = build_context("t2")
        assert ctx1.trace_id != ctx2.trace_id
        assert ctx1.request_id != ctx2.request_id

    def test_request_time_is_set(self):
        ctx = build_context("t")
        assert ctx.request_time is not None


class TestInferSkillName:
    def test_known_database_tools(self):
        for tool in ["execute_sql_text", "execute_sql_file", "validate_sql", "list_datasources", "get_execution_status"]:
            assert _infer_skill_name(tool) == "database"

    def test_unknown_tool(self):
        assert _infer_skill_name("random_tool") == "unknown"


# ============================================================
# P0-3 第二轮补齐：覆盖 context.py L36-39（identity 分支）+ L54-65（_build_request_summary 分支）
# ============================================================


class TestBuildContextOperatorBranches:
    """L36-39: build_context 的 operator 两个分支"""

    def test_operator_从_identity读取_username(self):
        """L36-37: identity 已 set 时，operator = identity['username']"""
        from platform_mcp.mcp_server import _mcp_identity_var

        identity = {"user_id": 1, "username": "alice", "role_code": "developer"}
        token = _mcp_identity_var.set(identity)
        try:
            ctx = build_context("execute_sql_text")
            assert ctx.operator == "alice"
        finally:
            _mcp_identity_var.reset(token)

    def test_operator_未set_回退_operator_role(self):
        """L38-39: identity 未 set 时，operator = mcp://{operator_role}"""
        from platform_mcp.mcp_server import _mcp_identity_var

        token = _mcp_identity_var.set(None)
        try:
            with patch("platform_mcp.config.get_settings") as mock_gs:
                mock_gs.return_value.mcp.operator_role = "fallback_role"
                ctx = build_context("execute_sql_text")
                assert ctx.operator == "mcp://fallback_role"
        finally:
            _mcp_identity_var.reset(token)


class TestBuildRequestSummaryBranches:
    """L52-65: _build_request_summary 三个分支"""

    def test_有_sql_text_返回_sql_预览(self):
        """L54-56: kwargs 含 sql_text → 'tool=xxx sql=...'（≤500 字符）"""
        sql = "SELECT * FROM users"
        summary = _build_request_summary("execute_sql_text", {"sql_text": sql})
        assert summary == f"tool=execute_sql_text sql={sql}"

    def test_有_sql_text_超长_截断至_500(self):
        """L56: sql_text > 500 字符时截断"""
        long_sql = "SELECT " + "a" * 600
        summary = _build_request_summary("execute_sql_text", {"sql_text": long_sql})
        assert len(summary) <= 500 + len("tool=execute_sql_text sql=")
        assert summary.startswith("tool=execute_sql_text sql=SELECT ")

    def test_有_file_path_读取文件成功(self, tmp_path):
        """L57-62: kwargs 含 file_path → 读取文件内容前 400 字符"""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 1;", encoding="utf-8")
        summary = _build_request_summary("execute_sql_file", {"file_path": str(sql_file)})
        assert "tool=execute_sql_file" in summary
        assert "SELECT 1" in summary

    def test_有_file_path_读取失败_回退_file_only(self):
        """L63-64: file_path 文件不存在 → try/except 回退到 'tool=xxx file=...'"""
        summary = _build_request_summary("execute_sql_file", {"file_path": "/nonexistent/path.sql"})
        assert summary == "tool=execute_sql_file file=/nonexistent/path.sql"

    def test_无_sql_无_file_返回_tool_only(self):
        """L65: kwargs 无 sql_text/file_path → 'tool=xxx'"""
        summary = _build_request_summary("list_datasources", {})
        assert summary == "tool=list_datasources"


# ============================================================
# Server Skill 审计摘要补充（Issue 3：upload/download/execute_command 抓路径）
# ============================================================


class TestBuildRequestSummaryServerBranches:
    """Server Skill 工具的 request_summary 摘要补充"""

    def test_upload_file_含_server_路径(self):
        summary = _build_request_summary(
            "upload_file",
            {
                "server_code": "linux-app-dev",
                "local_path": "/tmp/a.txt",
                "remote_path": "/home/cast/a.txt",
            },
        )
        assert "tool=upload_file" in summary
        assert "server=linux-app-dev" in summary
        assert "local=/tmp/a.txt" in summary
        assert "remote=/home/cast/a.txt" in summary

    def test_download_file_含_server_路径(self):
        summary = _build_request_summary(
            "download_file",
            {
                "server_code": "linux-app-dev",
                "remote_path": "/var/log/syslog",
                "local_path": "/tmp/syslog",
            },
        )
        assert "tool=download_file" in summary
        assert "server=linux-app-dev" in summary
        assert "remote=/var/log/syslog" in summary
        assert "local=/tmp/syslog" in summary

    def test_execute_command_含_server_前缀(self):
        summary = _build_request_summary(
            "execute_command",
            {"server_code": "linux-app-dev", "command": "ls -la"},
        )
        assert summary == "tool=execute_command server=linux-app-dev cmd=ls -la"

    def test_execute_command_无_server_code_回退(self):
        summary = _build_request_summary("execute_command", {"command": "whoami"})
        assert summary == "tool=execute_command cmd=whoami"

    def test_upload_file_超长_截断_500(self):
        long_path = "a" * 600
        summary = _build_request_summary(
            "upload_file",
            {
                "server_code": "srv1",
                "local_path": f"/tmp/{long_path}",
                "remote_path": f"/remote/{long_path}",
            },
        )
        assert len(summary) <= 500


class TestMcpContextDataclassFields:
    """L10-22: dataclass 字段默认值验证"""

    def test_optional_fields_默认_None(self):
        ctx = McpContext(
            trace_id="t1",
            request_id="r1",
            operator="op",
            skill_name="database",
            tool_name="execute_sql_text",
        )
        assert ctx.target_datasource is None
        assert ctx.target_env is None
        assert ctx.risk_level is None
        assert ctx.request_summary is None
        assert ctx.extra_data is None

    def test_request_time_自动填充(self):
        ctx = McpContext(
            trace_id="t1",
            request_id="r1",
            operator="op",
            skill_name="database",
            tool_name="execute_sql_text",
        )
        assert ctx.request_time is not None

