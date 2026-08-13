"""MCP 调用上下文构建 — 对应架构文档 §8.6"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class McpContext:
    trace_id: str
    request_id: str
    operator: str
    skill_name: str
    tool_name: str
    target_datasource: str | None = None
    target_env: str | None = None
    request_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    risk_level: str | None = None
    request_summary: str | None = None
    extra_data: dict | None = None
    source_session: dict | None = None


def build_context(tool_name: str, **kwargs: object) -> McpContext:
    """从 Tool 调用参数构建 McpContext。

    operator 优先从 MCP 认证身份读取（API Key 校验结果）；
    未设置时回退到 settings.mcp.operator_role（兼容无 Key 的遗留场景）。
    """
    from platform_mcp.config import get_settings
    from platform_mcp.mcp_server import get_current_identity

    settings = get_settings()
    identity = get_current_identity()
    if identity:
        operator = identity["username"]
    else:
        operator = f"mcp://{settings.mcp.operator_role}"
    return McpContext(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        operator=operator,
        skill_name=_infer_skill_name(tool_name),
        tool_name=tool_name,
        target_datasource=kwargs.get("datasource_code"),  # type: ignore[arg-type]
        target_env=kwargs.get("env_code"),  # type: ignore[arg-type]
        request_summary=_build_request_summary(tool_name, kwargs),
    )


def _build_request_summary(tool_name: str, kwargs: dict) -> str:
    """从 kwargs 提取 SQL / Shell 命令 / SFTP 路径预览（≤500 字符）作为审计 request_summary。"""
    sql_text = kwargs.get("sql_text")
    if sql_text:
        return f"tool={tool_name} sql={str(sql_text)[:500]}"
    file_path = kwargs.get("file_path")
    if file_path:
        try:
            from pathlib import Path
            content = Path(str(file_path)).read_text(encoding="utf-8")
            return f"tool={tool_name} file={file_path} sql={content[:400]}"
        except Exception:
            return f"tool={tool_name} file={file_path}"
    # server skill：upload_file / download_file / execute_command 都带 server_code
    server_code = kwargs.get("server_code")
    local_path = kwargs.get("local_path")
    remote_path = kwargs.get("remote_path")
    if tool_name in ("upload_file", "download_file") and local_path and remote_path:
        return (
            f"tool={tool_name} server={server_code} "
            f"local={local_path} remote={remote_path}"
        )[:500]
    command = kwargs.get("command")
    if command:
        if server_code:
            prefix = f"tool={tool_name} server={server_code} "
        else:
            prefix = f"tool={tool_name} "
        return f"{prefix}cmd={str(command)[: (500 - len(prefix))]}"
    execution_id = kwargs.get("execution_id")
    if execution_id:
        return f"tool={tool_name} execution_id={execution_id}"
    env_code = kwargs.get("env_code")
    if env_code:
        return f"tool={tool_name} env={env_code}"
    return f"tool={tool_name}"


def _infer_skill_name(tool_name: str) -> str:
    """根据 tool_name 推断所属 Skill。"""
    database_tools = {
        "execute_sql_file",
        "execute_sql_text",
        "validate_sql",
        "list_datasources",
        "get_execution_status",
    }
    server_tools = {
        "execute_command",
        "upload_file",
        "download_file",
        "list_servers",
        "validate_command",
        "get_server_execution_status",
    }
    if tool_name in database_tools:
        return "database"
    if tool_name in server_tools:
        return "server"
    return "unknown"
