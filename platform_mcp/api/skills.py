"""Skill 管理 API"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.registry import get_skill_instance, registry

router = APIRouter(prefix="/skills", tags=["Skill 管理"])

STATUS_MAP = {"ENABLED": 1, "DISABLED": 0, "PENDING_REVIEW": 2, "REJECTED": 3}
STATUS_REVERSE = {v: k for k, v in STATUS_MAP.items()}


class SkillCreateRequest(BaseModel):
    skill_code: str
    skill_name: str
    description: str | None = None


class SkillStatusRequest(BaseModel):
    status: str


class SkillReviewRequest(BaseModel):
    action: str
    comment: str | None = None


@router.get("")
async def list_skills(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    query = select(PmcpSkill)
    count_query = select(func.count()).select_from(PmcpSkill)
    if search:
        clause = PmcpSkill.skill_code.ilike(f"%{search}%") | PmcpSkill.skill_name.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    if status and status in STATUS_MAP:
        query, count_query = query.where(PmcpSkill.status == STATUS_MAP[status]), count_query.where(
            PmcpSkill.status == STATUS_MAP[status]
        )
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpSkill.id)
    skills = (await db.execute(query)).scalars().all()
    items = []
    for s in skills:
        # 动态实例化 Skill 获取真实 tool_count，避免依赖 DB 静态字段或 web 空的 registry
        instance = get_skill_instance(s.skill_code)
        if instance is not None:
            tool_count = len(instance.list_tools())
            tool_names = [m.tool_name for m in instance.list_tools()]
        else:
            tool_count = s.tool_count or 0
            tool_names = []
        items.append(
            {
                "id": s.id,
                "skill_code": s.skill_code,
                "skill_name": s.skill_name,
                "description": s.description,
                "status": STATUS_REVERSE.get(s.status, "UNKNOWN"),
                "tool_count": tool_count,
                "tool_names": tool_names,
                "register_method": s.register_method,
                "submitted_by": s.inserted_by,
                "created_at": s.inserted_at.isoformat() if s.inserted_at else None,
            }
        )
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("")
async def create_skill(
    body: SkillCreateRequest, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    # TODO(phase-2): 页面新增 Skill 功能二期实现，当前返回 501
    from fastapi import HTTPException

    raise HTTPException(status_code=501, detail="页面新增 Skill 为二期功能，暂未开放")


@router.put("/{skill_id}/status")
async def update_skill_status(
    skill_id: int, body: SkillStatusRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    skill = await db.get(PmcpSkill, skill_id)
    if not skill:
        return ResponseBase(code=10002, message="Skill 不存在")
    old_status = STATUS_REVERSE.get(skill.status, "UNKNOWN")
    skill.status = STATUS_MAP.get(body.status, skill.status)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="config",
        resource_id=str(skill_id),
        request_summary=f"修改 Skill 状态: {skill.skill_code}, {old_status} -> {body.status}",
        result_status="success",
        extra_data={"skill_code": skill.skill_code, "old_status": old_status, "new_status": body.status},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="状态更新成功")


@router.post("/{skill_id}/review")
async def review_skill(
    skill_id: int, body: SkillReviewRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    skill = await db.get(PmcpSkill, skill_id)
    if not skill:
        return ResponseBase(code=10002, message="Skill 不存在")
    old_status = STATUS_REVERSE.get(skill.status, "UNKNOWN")
    if body.action == "approve":
        skill.status = 1
    elif body.action == "reject":
        skill.status = 3
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="config",
        resource_id=str(skill_id),
        request_summary=f"审核 Skill: {skill.skill_code}, 动作: {body.action}",
        result_status="success",
        extra_data={"skill_code": skill.skill_code, "action": body.action, "old_status": old_status},
        duration_ms=duration_ms,
    )
    return ResponseBase(message=f"审核完成: {body.action}")
