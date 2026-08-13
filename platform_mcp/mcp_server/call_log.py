"""MCP 调用日志 — 写入 pmcp_mcp_call_log + pmcp_audit_log"""

from __future__ import annotations

from loguru import logger

from platform_mcp.mcp_server.context import McpContext

_SQL_TOOLS = {"execute_sql_text", "execute_sql_file", "validate_sql", "get_execution_status"}
_SHELL_TOOLS = {"execute_command", "upload_file", "download_file", "validate_command", "get_server_execution_status"}


def _infer_resource_type(tool_name: str) -> str:
    """按 tool_name 推断审计 resource_type。
    SQL 执行类 → 'sql'；Shell/SFTP 执行类 → 'shell'；元数据查询类（list_datasources / list_servers）→ 'datasource'/'server'。
    """
    if tool_name in _SQL_TOOLS:
        return "sql"
    if tool_name in _SHELL_TOOLS:
        return "shell"
    if tool_name in {"list_servers", "get_server_execution_status"}:
        return "server"
    return "datasource"


async def log_mcp_call(
    context: McpContext,
    result_status: str,
    duration_ms: int,
    error: str | None = None,
    error_code: str | None = None,
) -> None:
    """记录 MCP 调用日志到数据库。异常仅打印警告，不中断主流程。"""
    try:
        from platform_mcp.audit.logger import write_audit_log
        from platform_mcp.common.database import get_session_factory

        from platform_mcp.audit.models import PmcpMcpCallLog

        async with get_session_factory()() as session:
            # input_summary 拼接 skill + 实际请求摘要（含 SQL/command 文本，截断 500 字符）
            summary = context.request_summary or f"tool={context.tool_name}"
            input_summary = f"skill={context.skill_name} | {summary}"[:500]
            call_log = PmcpMcpCallLog(
                trace_id=context.trace_id,
                tool_name=context.tool_name,
                caller=context.operator,
                datasource_code=context.target_datasource,
                env_code=context.target_env,
                input_summary=input_summary,
                output_summary=error or result_status,
                result_status=result_status,
                error_code=error_code,
                error_message=error,
                duration_ms=duration_ms,
                confirm_token=None,
                inserted_by=context.operator,
            )
            session.add(call_log)
            await session.commit()

        merged_extra = {**(context.extra_data or {})}
        if context.source_session:
            merged_extra["source_session"] = context.source_session
        await write_audit_log(
            trace_id=context.trace_id,
            request_id=context.request_id,
            operator=context.operator,
            skill_name=context.skill_name,
            tool_name=context.tool_name,
            resource_type=_infer_resource_type(context.tool_name),
            resource_id=context.target_datasource,
            env_code=context.target_env,
            request_summary=context.request_summary or f"tool={context.tool_name}",
            result_status=result_status,
            risk_level=context.risk_level,
            extra_data=merged_extra or None,
            duration_ms=duration_ms,
            error_code=error_code,
            error_message=error,
        )
    except Exception:
        logger.warning("failed to write MCP call log (non-fatal)", exc_info=True)
