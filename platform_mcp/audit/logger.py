"""审计日志基础设施"""

from __future__ import annotations

import time
from datetime import datetime, timezone

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
