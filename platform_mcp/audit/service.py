"""审计日志查询服务"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.models import PmcpAuditLog


async def query_logs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    operator: str | None = None,
    skill_name: str | None = None,
    tool_name: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_summary: str | None = None,
    risk_level: str | None = None,
    result_status: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> tuple[list[dict], int]:
    query = select(PmcpAuditLog)
    count_query = select(func.count()).select_from(PmcpAuditLog)

    if operator:
        query, count_query = query.where(PmcpAuditLog.operator.ilike(f"%{operator}%")), count_query.where(
            PmcpAuditLog.operator.ilike(f"%{operator}%")
        )
    if resource_type:
        query, count_query = query.where(PmcpAuditLog.resource_type == resource_type), count_query.where(
            PmcpAuditLog.resource_type == resource_type
        )
    if resource_id:
        query, count_query = query.where(PmcpAuditLog.resource_id == resource_id), count_query.where(
            PmcpAuditLog.resource_id == resource_id
        )
    if request_summary:
        query, count_query = query.where(PmcpAuditLog.request_summary.ilike(f"%{request_summary}%")), count_query.where(
            PmcpAuditLog.request_summary.ilike(f"%{request_summary}%")
        )
    if skill_name:
        query, count_query = query.where(PmcpAuditLog.skill_name.ilike(f"%{skill_name}%")), count_query.where(
            PmcpAuditLog.skill_name.ilike(f"%{skill_name}%")
        )
    if tool_name:
        query, count_query = query.where(PmcpAuditLog.tool_name.ilike(f"%{tool_name}%")), count_query.where(
            PmcpAuditLog.tool_name.ilike(f"%{tool_name}%")
        )
    if risk_level:
        query, count_query = query.where(PmcpAuditLog.risk_level == risk_level), count_query.where(
            PmcpAuditLog.risk_level == risk_level
        )
    if result_status:
        query, count_query = query.where(PmcpAuditLog.result_status == result_status), count_query.where(
            PmcpAuditLog.result_status == result_status
        )
    if start_time:
        query, count_query = query.where(PmcpAuditLog.inserted_at >= start_time), count_query.where(
            PmcpAuditLog.inserted_at >= start_time
        )
    if end_time:
        query, count_query = query.where(PmcpAuditLog.inserted_at <= end_time), count_query.where(
            PmcpAuditLog.inserted_at <= end_time
        )

    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpAuditLog.id.desc())
    logs = (await db.execute(query)).scalars().all()

    items = []
    for log in logs:
        items.append(
            {
                "id": log.id,
                "trace_id": log.trace_id,
                "operator": log.operator,
                "skill_name": log.skill_name,
                "tool_name": log.tool_name,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "env_code": log.env_code,
                "request_summary": log.request_summary,
                "risk_level": log.risk_level,
                "result_status": log.result_status,
                "error_code": log.error_code,
                "duration_ms": log.duration_ms,
                "error_message": log.error_message,
                "extra_data": log.extra_data,
                "created_at": log.inserted_at.astimezone().strftime("%Y-%m-%d %H:%M:%S") if log.inserted_at else None,
            }
        )
    return items, total


def _pct_change(today: int, yesterday: int) -> float | None:
    """Compute percentage change from yesterday to today. Returns None when yesterday is 0."""
    if yesterday == 0:
        return None
    return round((today - yesterday) / yesterday * 100, 2)


async def _count_for_period(
    db: AsyncSession,
    start: datetime,
    end: datetime,
    operator: str | None,
) -> dict[str, int]:
    """Return the four stat counters for a given date range."""
    base = [PmcpAuditLog.inserted_at >= start, PmcpAuditLog.inserted_at < end]
    if operator:
        base.append(PmcpAuditLog.operator == operator)

    total_q = select(func.count()).select_from(PmcpAuditLog)
    mcp_q = select(func.count()).select_from(PmcpAuditLog).where(PmcpAuditLog.skill_name.isnot(None))
    sql_q = select(func.count()).select_from(PmcpAuditLog).where(PmcpAuditLog.tool_name.isnot(None))
    high_q = select(func.count()).select_from(PmcpAuditLog).where(PmcpAuditLog.risk_level.in_(["HIGH", "CRITICAL"]))

    for f in base:
        total_q, mcp_q, sql_q, high_q = total_q.where(f), mcp_q.where(f), sql_q.where(f), high_q.where(f)

    return {
        "total_operations": (await db.execute(total_q)).scalar() or 0,
        "mcp_calls": (await db.execute(mcp_q)).scalar() or 0,
        "sql_executions": (await db.execute(sql_q)).scalar() or 0,
        "high_risk_blocks": (await db.execute(high_q)).scalar() or 0,
    }


async def get_stats(db: AsyncSession, operator: str | None = None) -> dict:
    today_start = datetime.combine(date.today(), datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)
    yesterday_start = today_start - timedelta(days=1)

    today_stats = await _count_for_period(db, today_start, tomorrow_start, operator)
    yesterday_stats = await _count_for_period(db, yesterday_start, today_start, operator)

    trends = {}
    for key in ("total_operations", "mcp_calls", "sql_executions", "high_risk_blocks"):
        trends[f"{key}_vs_yesterday"] = _pct_change(today_stats[key], yesterday_stats[key])

    return {**today_stats, "trends": trends}
