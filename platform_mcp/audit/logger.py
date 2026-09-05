"""审计日志基础设施（V3.0 M5 起兼任邮件提醒单一咽喉，架构 §19.5.5）"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.common import database as _db


async def write_audit_log(
    trace_id: str | None = None,
    request_id: str | None = None,
    operator: str | None = None,
    skill_name: str | None = None,
    tool_name: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    env_code: str | None = None,
    request_summary: str | None = None,
    result_status: str | None = None,
    risk_level: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    extra_data: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    """异步写入审计日志到 pmcp_audit_log"""
    from platform_mcp.audit.models import PmcpAuditLog

    async with _db.get_session_factory()() as session:
        log = PmcpAuditLog(
            trace_id=trace_id,
            request_id=request_id,
            operator=operator,
            skill_name=skill_name,
            tool_name=tool_name,
            resource_type=resource_type,
            resource_id=resource_id,
            env_code=env_code,
            request_summary=request_summary,
            result_status=result_status,
            risk_level=risk_level,
            error_code=error_code,
            error_message=error_message,
            extra_data=extra_data,
            duration_ms=duration_ms,
            inserted_by=operator,
        )
        session.add(log)
        await session.commit()
    await _route_high_risk_notify(
        trace_id=trace_id,
        operator=operator,
        resource_type=resource_type,
        resource_id=resource_id,
        env_code=env_code,
        request_summary=request_summary,
        risk_level=risk_level,
    )


# ==================== V3.0 M5：生产高危操作邮件路由（§19.5.5 捕捉点）====================

# resource_type → notify_type（call_log._infer_resource_type / Web API 审计口径的并集）
_DB_RESOURCE_TYPES = {"sql", "datasource"}
_SERVER_RESOURCE_TYPES = {"shell", "server"}
_HIGH_RISK_LEVELS = {"HIGH", "CRITICAL"}


def _resolve_high_risk_notify_type(resource_type: str | None, risk_level: str | None,
                                   env_code: str | None) -> str | None:
    """命中条件：PROD 环境 + HIGH/CRITICAL 风险 + 数据库/服务器类资源 → 对应 notify_type。

    单一咽喉：本函数挂在 write_audit_log 内部，Web 与 MCP 双入口（call_log → 本函数）
    的高危执行操作无需各自挂接（§19.5.5）；未命中（DEV/UAT、LOW/MEDIUM、非执行类、
    无 risk_level）返回 None。
    """
    if env_code != "PROD" or (risk_level or "").upper() not in _HIGH_RISK_LEVELS:
        return None
    if resource_type in _DB_RESOURCE_TYPES:
        return "db_high_op"
    if resource_type in _SERVER_RESOURCE_TYPES:
        return "server_high_op"
    return None


async def _route_high_risk_notify(
    *,
    trace_id: str | None,
    operator: str | None,
    resource_type: str | None,
    resource_id: str | None,
    env_code: str | None,
    request_summary: str | None,
    risk_level: str | None,
) -> None:
    """审计落库后路由邮件组（outbox 落库，不发送）；异常全捕获不阻断审计调用方。"""
    notify_type = _resolve_high_risk_notify_type(resource_type, risk_level, env_code)
    if notify_type is None:
        return
    try:
        from platform_mcp.notify.service import dispatch_notification

        await dispatch_notification(
            notify_type,
            {
                "user": operator or "-",
                "resource": resource_id or "-",
                "env": env_code or "-",
                "risk": (risk_level or "").upper(),
                "summary": (request_summary or "")[:500],
            },
            source="audit_route",
            trace_id=trace_id,
            operator=operator,
        )
    except Exception:  # noqa: BLE001 - 通知路由故障不影响审计主链路
        from loguru import logger

        logger.warning("high-risk notify route failed (non-fatal)", exc_info=True)
