"""Skill 管理 API"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.registry import get_skill_instance
from platform_mcp.skills.audit.models import PmcpSkillAuditReport
from platform_mcp.skills.upload import process_skill_upload

router = APIRouter(prefix="/skills", tags=["Skill 管理"])

# V3.0（migration 005）：pmcp_skill.status 由 SMALLINT 转 VARCHAR 状态机，API 值域不变
STATUS_MAP = {
    "DRAFT": "DRAFT",
    "PENDING_REVIEW": "PENDING_REVIEW",
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "SHARE_ITERATION": "SHARE_ITERATION",
    "ENABLED": "ENABLED",
    "DISABLED": "DISABLED",
    "WITHDRAWN": "WITHDRAWN",
}
STATUS_REVERSE = {v: k for k, v in STATUS_MAP.items()}


class SkillStatusRequest(BaseModel):
    status: str


class SkillRenameRequest(BaseModel):
    """重命名请求（批次 6.1）：新 skill_code（owner-only，磁盘目录同步改名）。"""

    skill_code: str


class SkillReviewRequest(BaseModel):
    action: str
    comment: str | None = None
    iteration_note: str | None = None
    target_plaza_id: int | None = None


class SkillSubmitRequest(BaseModel):
    confirm_reshare: bool = False


class SkillResolveIterationRequest(BaseModel):
    choice: str  # iterate | keep


@router.get("")
async def list_skills(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from platform_mcp.review.service import ReviewActor, SkillReviewService
    from platform_mcp.skills.plaza import load_blocked_skill_ids

    query = select(PmcpSkill)
    if search:
        clause = PmcpSkill.skill_code.ilike(f"%{search}%") | PmcpSkill.skill_name.ilike(f"%{search}%")
        query = query.where(clause)
    if status and status in STATUS_MAP:
        query = query.where(PmcpSkill.status == STATUS_MAP[status])
    all_skills = (await db.execute(query.order_by(PmcpSkill.id))).scalars().all()

    # F-27 个人库可见性矩阵（查询层落地，避免装饰性）：草稿/已拒绝/撤回仅本人可见（含 admin 不可见），
    # 内置装饰器 Skill 仅 admin 可见，未分享已启用仅本人可见。委托状态机单一事实来源；
    # Skill 量级 < 数千（VNF-02），Python 层过滤 + 分页与矩阵保持一致，不下推 SQL 以免逻辑双写。
    # F-34 黑名单双端过滤：用户屏蔽的个人 Skill（target_skill_id）Web 端不再出现（仅黑名单页可见）。
    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    blocked_ids = await load_blocked_skill_ids(db, current_user.get("id"))
    visible_skills = [
        s for s in all_skills if s.id not in blocked_ids and service.is_visible_to(actor, s)
    ]
    total = len(visible_skills)
    start = (page - 1) * page_size
    skills = visible_skills[start : start + page_size]
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
                "version": s.version,
                "source_format": s.source_format,
                "share_status": s.share_status,
                "origin": s.origin,
                "plaza_id": s.plaza_id,
                "review_comment": s.review_comment,
            }
        )
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.get("/pending")
async def list_pending_skills(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """待审提交列表（批次 7.1，admin）：PENDING_REVIEW 全量分页，附提交人/通道/时间/版本与同名比对素材。"""
    from platform_mcp.skills.plaza import compute_name_match

    rows = (
        await db.execute(
            select(PmcpSkill).where(PmcpSkill.status == "PENDING_REVIEW").order_by(PmcpSkill.id)
        )
    ).scalars().all()
    total = len(rows)
    start = (page - 1) * page_size
    items = []
    for s in rows[start : start + page_size]:
        name_match = await compute_name_match(db, s.skill_name or "", s.description)
        items.append(
            {
                "id": s.id,
                "skill_code": s.skill_code,
                "skill_name": s.skill_name,
                "description": s.description,
                "status": "PENDING_REVIEW",
                "register_method": s.register_method,
                "submitted_by": s.inserted_by,
                "created_at": s.inserted_at.isoformat() if s.inserted_at else None,
                "version": s.version,
                "origin": s.origin,
                "plaza_id": s.plaza_id,
                "audit_status": s.audit_status,
                "review_comment": s.review_comment,
                "name_match": name_match,
            }
        )
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.get("/{skill_id}/files")
async def get_skill_files(
    skill_id: int,
    path: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """审核文件预览（批次 7.1，admin）：无 path 返回包内文件清单；带 path 返回单文件内容（复用 MCP 包内路径防穿越）。"""
    from platform_mcp.review.service import SkillReviewError
    from platform_mcp.skills.ecosystem.plaza_tools import _read_package_file

    skill = await db.get(PmcpSkill, skill_id)
    if skill is None:
        return ResponseBase(code=10002, message="Skill 不存在")
    if path:
        try:
            data = _read_package_file(skill.source_path or "", path)
        except SkillReviewError as exc:
            return ResponseBase(code=exc.error_code, message=exc.message)
        return ResponseBase(data=data)
    root = Path(skill.source_path) if skill.source_path else None
    files: list[dict] = []
    if root and root.is_dir():
        for f in sorted(root.rglob("*")):
            if f.is_file():
                files.append({"path": f.relative_to(root).as_posix(), "size": f.stat().st_size})
    return ResponseBase(data={"skill_id": skill.id, "skill_code": skill.skill_code, "files": files})


@router.delete("/{skill_id}")
async def remove_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """移除个人库中自己的 Skill（Web 侧 ``remove_my_skill``，架构 §19.5.7，F-29）。

    仅本人可移除；内置装饰器 Skill（database/server）不可移除（返回 10003）；广场副本独立于个人库，
    移除个人复制体不影响广场。与 MCP ``remove_my_skill`` 共用同一编排（委托 plaza_service）。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError
    from platform_mcp.skills.plaza_service import remove_my_skill

    actor = ReviewActor.from_user_dict(current_user)
    try:
        await remove_my_skill(db, skill_id, actor)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(message="已移除")


@router.put("/{skill_id}")
async def rename_skill(
    skill_id: int,
    body: SkillRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """重命名自己的 Skill（批次 6.1，设计定稿⑩）：改 skill_code + 磁盘目录同步改名。

    仅本人（F-29，admin 亦不代改）；非内置装饰器、未分享（origin≠PLAZA 且 plaza_id 为空）、
    稳定态（DRAFT/REJECTED/WITHDRAWN/ENABLED/DISABLED）可改；与 MCP ``update_my_skill`` 的
    ``skill_code`` 参数共用 :func:`platform_mcp.skills.personal.rename_my_skill`（同条件矩阵同审计）。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError
    from platform_mcp.skills.personal import rename_my_skill

    actor = ReviewActor.from_user_dict(current_user)
    try:
        skill = await rename_my_skill(db, skill_id, body.skill_code, actor)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(message="已重命名", data={"skill_id": skill.id, "skill_code": skill.skill_code})


@router.post("/upload")
async def upload_skill(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Skill 包上传：.7z/.zip → 解压 → 审计 → 脱敏 → README → 存储 → 注册

    M4.2：同步以确定性模板即时存档（F-28 即时性），响应返回后 ``BackgroundTasks`` 后台升级
    ``generated_by=template → model``（本地 Qwen3 产物 + 重放校验门禁；模型缺失/失败保留模板，
    VNF-01 不阻塞上传链路）。
    """
    start = time.monotonic()

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    lower_name = file.filename.lower()
    if not (lower_name.endswith(".zip") or lower_name.endswith(".7z")):
        raise HTTPException(status_code=400, detail="仅支持 .zip 和 .7z 格式")

    from platform_mcp.common.runtime_config import runtime_config

    max_upload_size_mb = int(await runtime_config.get("skill.max_upload_size_mb"))
    max_size = max_upload_size_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（最大 {max_upload_size_mb}MB）",
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

        # M4.2：后台升级版本存档为本地模型产物（独立 session；失败保留模板兜底，VNF-01）
        from platform_mcp.skills.llm.tasks import upgrade_version_artifacts

        if result.skill_id is not None:
            background_tasks.add_task(
                upgrade_version_artifacts, result.skill_id, result.version,
                operator=current_user["username"],
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        await write_audit_log(
            operator=current_user["username"],
            resource_type="skill",
            resource_id=result.skill_code,
            request_summary=f"上传 Skill 包: {file.filename}",
            result_status="success",
            extra_data={
                "action": "update" if result.is_update else "create",
                "channel": "web",
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
            "readme_generated": result.readme_generated,
            "source_format": result.source_format,
            "skill_id": result.skill_id,
            "is_update": result.is_update,
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
    current_user: dict = Depends(get_current_user),
):
    """Web 启停（批次 6.3 状态机统一，废除 admin 直写 STATUS_MAP）：

    - 个人 Skill（非内置、origin≠PLAZA）：委托 ``SkillReviewService.set_enabled``（owner 或 admin，
      ENABLED↔DISABLED 经 8 状态机；PENDING_REVIEW 停用视同撤回 F-32；审计由服务统一落痕）；
    - 内置装饰器 / 广场复制（origin=PLAZA）：仅 admin，ENABLED/DISABLED 直写（§19.5.7 该两类
      仅 Web admin 可调整，不经个人状态机）。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    if body.status not in ("ENABLED", "DISABLED"):
        return ResponseBase(code=10003, message="status 仅支持 ENABLED / DISABLED")

    actor = ReviewActor.from_user_dict(current_user)
    skill = await db.get(PmcpSkill, skill_id)
    if not skill:
        return ResponseBase(code=10002, message="Skill 不存在")

    if skill.register_method == "decorator" or skill.origin == "PLAZA":
        if not actor.is_admin:
            return ResponseBase(code=10004, message="内置装饰器 / 广场复制 Skill 仅 admin 可调整")
        start = time.monotonic()
        old_status = STATUS_REVERSE.get(skill.status, "UNKNOWN")
        skill.status = body.status
        await db.flush()
        duration_ms = int((time.monotonic() - start) * 1000)
        await write_audit_log(
            operator=current_user["username"],
            resource_type="skill",
            resource_id=str(skill_id),
            request_summary=f"修改 Skill 状态: {skill.skill_code}, {old_status} -> {body.status}",
            result_status="success",
            extra_data={
                "action": "enable" if body.status == "ENABLED" else "disable",
                "channel": "web",
                "skill_code": skill.skill_code,
                "old_status": old_status,
                "new_status": body.status,
                "admin_direct": True,
            },
            duration_ms=duration_ms,
        )
        return ResponseBase(message="状态更新成功")

    service = SkillReviewService(db)
    try:
        result = await service.set_enabled(actor, skill_id, body.status == "ENABLED")
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(message="状态更新成功", data={
        "old_status": result.old_status,
        "new_status": result.new_status,
    })


@router.post("/{skill_id}/review")
async def review_skill(
    skill_id: int,
    body: SkillReviewRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """Skill 广场审核（admin）：approve 新增入广场 / merge 合并 / reject 拒绝。

    委托 :class:`platform_mcp.review.service.SkillReviewService`（8 状态机 + 广场副本 upsert +
    ``resource_type="skill"`` 审计，F-40/F-43），与 MCP 通道共用同一编排，避免 Web 侧装饰性直改状态。
    业务错误（不存在/非法状态/非 admin）转统一响应码（HTTP 200 + code），保持既有 API 契约。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    if body.action not in ("approve", "merge", "reject"):
        raise HTTPException(status_code=400, detail="action 必须为 approve/merge/reject")

    actor = ReviewActor.from_user_dict(_admin)
    service = SkillReviewService(db)
    try:
        result = await service.review(
            actor,
            skill_id,
            body.action,  # type: ignore[arg-type]
            comment=body.comment,
            iteration_note=body.iteration_note,
            target_plaza_id=body.target_plaza_id,
        )
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)

    reports = (
        await db.execute(
            select(PmcpSkillAuditReport)
            .where(PmcpSkillAuditReport.skill_id == skill_id)
            .order_by(PmcpSkillAuditReport.id)
        )
    ).scalars().all()

    return ResponseBase(data={
        "skill_id": result.skill_id,
        "skill_code": result.skill_code,
        "action": result.action,
        "old_status": result.old_status,
        "new_status": result.new_status,
        "share_status": result.share_status,
        "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
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


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Skill 版本化存档查询（F-28）：返回按版本存档的双语 README / 审核报告（不可篡改）。

    前端 README 图标弹窗（按 locale 取 readme_zh/readme_en）与 admin 审核弹窗
    （报告含广场比对推荐结论 + README）共用本端点；versions[0] 为最新存档。
    """
    from platform_mcp.skills.models import PmcpSkillVersion

    skill = await db.get(PmcpSkill, skill_id)
    if not skill:
        return ResponseBase(code=10002, message="Skill 不存在")
    versions = (
        await db.execute(
            select(PmcpSkillVersion)
            .where(PmcpSkillVersion.skill_id == skill_id)
            .order_by(PmcpSkillVersion.id.desc())
        )
    ).scalars().all()
    return ResponseBase(data={
        "skill_id": skill_id,
        "skill_code": skill.skill_code,
        "current_version": skill.version,
        "versions": [
            {
                "version": v.version,
                "checksum": v.checksum,
                "generated_by": v.generated_by,
                "readme_zh": v.readme_zh,
                "readme_en": v.readme_en,
                "readme_extra": v.readme_extra,
                "report_zh": v.report_zh,
                "report_en": v.report_en,
                "report_extra": v.report_extra,
                "audit_snapshot": v.audit_snapshot,
                "created_at": v.inserted_at.isoformat() if v.inserted_at else None,
            }
            for v in versions
        ],
    })


@router.post("/{skill_id}/submit")
async def submit_skill_for_review(
    skill_id: int,
    body: SkillSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """owner 提交分享审核（Web 侧，委托 SkillReviewService）：DRAFT/ENABLED/DISABLED → PENDING_REVIEW。

    F-31 重复分享：已分享/审核中未带 ``confirm_reshare`` 返回 code=10005 要求二次确认（前端预检弹框）。
    与 MCP ``submit_skill_for_review`` 共用同一编排（F-43 双端可操作），审计 resource_type="skill"。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    try:
        result = await service.submit_for_review(actor, skill_id, confirm_reshare=body.confirm_reshare)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data={
        "skill_id": result.skill_id, "skill_code": result.skill_code, "action": result.action,
        "old_status": result.old_status, "new_status": result.new_status,
        "share_status": result.share_status, "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
    })


@router.post("/{skill_id}/withdraw")
async def withdraw_skill_review(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """owner 撤回审核（Web 侧，委托 SkillReviewService）：PENDING_REVIEW → WITHDRAWN（F-32）。

    与 MCP ``withdraw_review`` 共用同一编排（F-43）；停用视同撤回、邮件通知 admin 审核组由 M5 挂接。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    try:
        result = await service.withdraw(actor, skill_id)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data={
        "skill_id": result.skill_id, "skill_code": result.skill_code, "action": result.action,
        "old_status": result.old_status, "new_status": result.new_status,
        "share_status": result.share_status, "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
    })


@router.post("/{skill_id}/restore")
async def restore_skill_draft(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """owner 恢复草稿（Web 侧，委托 SkillReviewService）：WITHDRAWN → DRAFT。

    撤回后重新提交的轻量路径：无需重新上传包（重上传 upsert 的 RESTORE 联动与
    MCP ``update_my_skill`` 元数据更新同语义），恢复为草稿后可再次提交分享。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    try:
        result = await service.restore(actor, skill_id)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data={
        "skill_id": result.skill_id, "skill_code": result.skill_code, "action": result.action,
        "old_status": result.old_status, "new_status": result.new_status,
        "share_status": result.share_status, "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
    })


@router.post("/{skill_id}/revise")
async def revise_skill_draft(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """owner 重新编辑（Web 侧，委托 SkillReviewService）：REJECTED → DRAFT（保留拒绝原因供参考，重提审时覆盖）。"""
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    try:
        result = await service.revise(actor, skill_id)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data={
        "skill_id": result.skill_id, "skill_code": result.skill_code, "action": result.action,
        "old_status": result.old_status, "new_status": result.new_status,
        "share_status": result.share_status, "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
    })


@router.post("/{skill_id}/resolve-iteration")
async def resolve_skill_share_iteration(
    skill_id: int,
    body: SkillResolveIterationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """owner 解决分享迭代（Web 侧，委托 SkillReviewService）：SHARE_ITERATION → ENABLED（F-30）。

    ``iterate``=采纳合并（M4.3 内容级覆盖本地：广场快照复制回个人目录 + 重放审计 + 版本存档）；
    ``keep``=保留本地（忽略本次迭代）。与 MCP ``resolve_share_iteration`` 共用同一编排（F-43），
    选择后状态=已启用。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    if body.choice not in ("iterate", "keep"):
        raise HTTPException(status_code=400, detail="choice 必须为 iterate 或 keep")
    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    try:
        result = await service.resolve_share_iteration(actor, skill_id, body.choice)  # type: ignore[arg-type]
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data={
        "skill_id": result.skill_id, "skill_code": result.skill_code, "action": result.action,
        "old_status": result.old_status, "new_status": result.new_status,
        "share_status": result.share_status, "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
    })


@router.get("/{skill_id}/iteration-diff")
async def get_skill_iteration_diff(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """分享迭代差异查询（M4.3，F-30）：本地 vs 广场快照 SKILL.md 差异素材 + 双语描述。

    仅 SHARE_ITERATION 态、owner/admin 可查（委托 :meth:`SkillReviewService.build_iteration_diff`）；
    返回行级 unified diff / 行统计 / 语义相似度（BGE-M3 / 降级哈希）+ 双语差异描述（本地 Qwen3
    优先、模板兜底，``generated_by=model|template``）+ 性能提示（M4.4）。
    """
    from platform_mcp.review.service import ReviewActor, SkillReviewError, SkillReviewService

    actor = ReviewActor.from_user_dict(current_user)
    service = SkillReviewService(db)
    try:
        material = await service.build_iteration_diff(actor, skill_id)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data=material)