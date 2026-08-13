"""Skill 管理 API"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.config import get_settings
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.registry import get_skill_instance
from platform_mcp.skills.audit.models import PmcpSkillAuditReport
from platform_mcp.skills.upload import process_skill_upload

router = APIRouter(prefix="/skills", tags=["Skill 管理"])

STATUS_MAP = {"ENABLED": 1, "DISABLED": 0, "PENDING_REVIEW": 2, "REJECTED": 3}
STATUS_REVERSE = {v: k for k, v in STATUS_MAP.items()}


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
                "audit_status": s.audit_status,
                "readme_generated": s.readme_generated,
            }
        )
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("/upload")
async def upload_skill(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Skill 包上传：.7z/.zip → 解压 → 审计 → 脱敏 → README → 存储 → 注册"""
    start = time.monotonic()

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    lower_name = file.filename.lower()
    if not (lower_name.endswith(".zip") or lower_name.endswith(".7z")):
        raise HTTPException(status_code=400, detail="仅支持 .zip 和 .7z 格式")

    settings = get_settings()
    max_size = settings.skill.max_upload_size_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（最大 {settings.skill.max_upload_size_mb}MB）",
        )

    tmp_dir = tempfile.mkdtemp(prefix="skill_upload_raw_")
    try:
        tmp_path = Path(tmp_dir) / file.filename
        tmp_path.write_bytes(content)

        result = await process_skill_upload(
            file_path=tmp_path,
            original_filename=file.filename,
            db=db,
            operator=current_user["username"],
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        await write_audit_log(
            operator=current_user["username"],
            resource_type="config",
            resource_id=result.skill_code,
            request_summary=f"上传 Skill 包: {file.filename}",
            result_status="success",
            extra_data={
                "skill_code": result.skill_code,
                "audit_passed": not result.audit_result.critical_count > 0,
                "critical_count": result.audit_result.critical_count,
                "warning_count": result.audit_result.warning_count,
                "readme_generated": result.readme_generated,
            },
            duration_ms=duration_ms,
        )

        return ResponseBase(data={
            "skill_code": result.skill_code,
            "skill_name": result.skill_name,
            "description": result.description,
            "version": result.version,
            "audit_status": "failed" if result.audit_result.critical_count > 0
            else "warning" if result.audit_result.warning_count > 0
            else "passed",
            "audit_summary": result.audit_result.to_audit_summary(),
            "sanitization_passed": result.sanitization_passed,
            "readme_generated": result.readme_generated,
            "source_format": result.source_format,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.put("/{skill_id}/status")
async def update_skill_status(
    skill_id: int,
    body: SkillStatusRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
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
    skill_id: int,
    body: SkillReviewRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """Skill 审核：approve 或 reject，返回审核结果 + 审计报告"""
    start = time.monotonic()
    skill = await db.get(PmcpSkill, skill_id)
    if not skill:
        return ResponseBase(code=10002, message="Skill 不存在")

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须为 approve 或 reject")

    old_status = STATUS_REVERSE.get(skill.status, "UNKNOWN")
    if body.action == "approve":
        skill.status = 1  # ENABLED
    elif body.action == "reject":
        skill.status = 3  # REJECTED

    await db.commit()

    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="config",
        resource_id=str(skill_id),
        request_summary=f"审核 Skill: {skill.skill_code}, 动作: {body.action}",
        result_status="success",
        extra_data={"skill_code": skill.skill_code, "action": body.action, "old_status": old_status, "comment": body.comment},
        duration_ms=duration_ms,
    )

    reports = (
        await db.execute(
            select(PmcpSkillAuditReport)
            .where(PmcpSkillAuditReport.skill_id == skill_id)
            .order_by(PmcpSkillAuditReport.id)
        )
    ).scalars().all()

    return ResponseBase(data={
        "skill_code": skill.skill_code,
        "action": body.action,
        "old_status": old_status,
        "new_status": STATUS_REVERSE.get(skill.status, "UNKNOWN"),
        "audit_reports": [
            {
                "rule_id": r.rule_id,
                "severity": r.severity,
                "file_path": r.file_path,
                "line_number": r.line_number,
                "description": r.description,
                "suggestion": r.suggestion,
            }
            for r in reports
        ],
    })


@router.get("/{skill_id}/audit-report")
async def get_skill_audit_report(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """获取 Skill 审计报告详情"""
    skill = await db.get(PmcpSkill, skill_id)
    if not skill:
        return ResponseBase(code=10002, message="Skill 不存在")

    reports = (
        await db.execute(
            select(PmcpSkillAuditReport)
            .where(PmcpSkillAuditReport.skill_id == skill_id)
            .order_by(PmcpSkillAuditReport.id)
        )
    ).scalars().all()

    return ResponseBase(data={
        "skill_id": skill_id,
        "skill_code": skill.skill_code,
        "audit_status": skill.audit_status,
        "audit_summary": skill.audit_result,
        "reports": [
            {
                "id": r.id,
                "rule_id": r.rule_id,
                "severity": r.severity,
                "file_path": r.file_path,
                "line_number": r.line_number,
                "description": r.description,
                "suggestion": r.suggestion,
                "audit_time": r.audit_time.isoformat() if r.audit_time else None,
            }
            for r in reports
        ],
    })