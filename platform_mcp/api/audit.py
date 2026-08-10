"""审计日志 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.service import get_stats, query_logs
from platform_mcp.auth.middleware import get_current_user
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase

router = APIRouter(prefix="/audit", tags=["审计日志"])


@router.get("/logs")
async def list_logs(
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
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role_code"] != "admin":
        operator = current_user["username"]
    items, total = await query_logs(
        db, page, page_size, operator, skill_name, tool_name, resource_type,
        resource_id, request_summary, risk_level, result_status, start_time, end_time
    )
    return ResponseBase(
        data=PageResult.create(items, total, page, page_size)
    )


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    operator = None if current_user["role_code"] == "admin" else current_user["username"]
    return ResponseBase(data=await get_stats(db, operator))


@router.get("/logs/{log_id}")
async def get_log(log_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    from platform_mcp.audit.models import PmcpAuditLog
    from platform_mcp.common.exceptions import AuthError

    log = await db.get(PmcpAuditLog, log_id)
    if not log:
        return ResponseBase(code=15001, message="日志不存在")
    if current_user["role_code"] != "admin" and log.operator != current_user["username"]:
        raise AuthError("权限不足：只能查看自己的审计日志")
    return ResponseBase(
        data={
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
            "error_message": log.error_message,
            "duration_ms": log.duration_ms,
            "extra_data": log.extra_data,
            "created_at": log.inserted_at.isoformat() if log.inserted_at else None,
        }
    )
