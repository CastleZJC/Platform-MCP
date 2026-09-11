"""Skill 广场公共池 API（V3.0 M3.1 / M3.3，架构 §19.5.3 / §19.5.6，计划 F-23/F-33/需求 1.1.4）

广场（``pmcp_skill_plaza``）为独立于个人库的公共池，本模块提供全角色可见的：

- ``GET /plaza``：分页列出对当前角色可见的已发布广场 Skill（一般用户不见涉库/涉服务器项，F-23；
  admin 附带已停用项供停用现状展示，其余角色仅 PUBLISHED）；
- ``GET /plaza/search``：语义搜索（BGE-M3 / 降级哈希向量 + 关键词兜底，F-33）；
- ``GET /plaza/{plaza_id}``：广场 Skill 详情（可见性校验 + blocked 标记）；
- ``GET /plaza/{plaza_id}/readme``：广场 Skill 双语 README（镜像 MCP ``get_skill_readme`` plaza 路径）；
- ``GET /plaza/{plaza_id}/versions``：广场版本列表（可见者只读，含 source_version / 文件数 / 审计结论）；
- ``POST /plaza/{plaza_id}/versions/{version}/rollback``：广场版本回退（仅 admin，设计定稿⑦：快照恢复 +
  持有者迭代标记 + README 回滚条目，不新建版本行）；
- ``POST /plaza/{plaza_id}/disable``：停用广场 Skill（仅 admin，停用后双端不可见，幂等）；
- merge 工作台（设计定稿④，2026-09-10，均仅 admin）：``POST /plaza/merge/build``（文件级并集 →
  临时包 + 冲突清单 + 审计预跑）/ ``GET /plaza/merge/{token}``（任务详情）/
  ``GET /plaza/merge/{token}/files?path=``（文件清单 / 单文件预览）/
  ``POST /plaza/merge/{token}/publish``（publish 发布全链路 / discard 丢弃），
  与 MCP ``build_merge_version`` / ``publish_merge_version`` 同一服务编排。

可见性判定统一委托 :mod:`platform_mcp.skills.plaza`（``plaza_visible_to_role`` / ``list_visible_plazas``），
与 MCP ``search_skills`` 双端共用同一过滤口径，避免 Web 侧装饰性放行。黑名单（F-34）屏蔽集合由
``load_blocked_plaza_ids`` 读侧加载并传入过滤（写侧 block/unblock 端点见 M3.4）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.auth.models import PmcpUser
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.review.service import (
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
    SkillReviewError,
)
from platform_mcp.skills.merge_service import list_plaza_versions, serialize_merge
from platform_mcp.skills.models import PmcpPlazaMerge, PmcpSkillPlaza
from platform_mcp.skills.plaza import (
    list_visible_plazas,
    load_blocked_plaza_ids,
    plaza_visible_to_role,
    search_visible_plazas,
)
from platform_mcp.skills.plaza_service import (
    block_skill,
    copy_plaza_to_personal,
    disable_plaza_skill,
    list_blocked_skills,
    rollback_plaza_version,
    unblock_skill,
)
from platform_mcp.skills.versioning import generate_bilingual_readme

router = APIRouter(prefix="/plaza", tags=["Skill 广场"])


class BlockRequest(BaseModel):
    plaza_id: int | None = None
    skill_id: int | None = None
    reason: str | None = None


class UnblockRequest(BaseModel):
    plaza_id: int | None = None
    skill_id: int | None = None


class PlazaCopyRequest(BaseModel):
    """复制到个人库的冲突二选一参数（批次 6.2，code=10006 后重传）。"""

    conflict_resolution: str | None = None  # overwrite | retry
    new_code: str | None = None


class MergeBuildRequest(BaseModel):
    plaza_id: int
    source_skill_ids: list[int]
    base_version: str | None = None
    target_version: str | None = None
    comment: str | None = None


class MergePublishRequest(BaseModel):
    action: str  # publish | discard
    resolutions: dict | None = None
    target_version: str | None = None
    comment: str | None = None


async def _uploader_map(db: AsyncSession, uploader_ids: list[int | None]) -> dict[int, dict]:
    """批量解析分享者展示信息（username/nickname），避免 N+1 查询。"""
    ids = {i for i in uploader_ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(PmcpUser).where(PmcpUser.id.in_(ids)))).scalars().all()
    return {u.id: {"username": u.username, "nickname": u.nickname} for u in rows}


def _serialize(plaza: PmcpSkillPlaza, uploader: dict | None = None, similarity: float | None = None) -> dict:
    """广场 Skill 序列化（involve_flags 供前端标记涉库/涉服务器，F-23）。"""
    data: dict = {
        "plaza_id": plaza.id,
        "skill_code": plaza.skill_code,
        "skill_name": plaza.skill_name,
        "description": plaza.description,
        "version": plaza.version,
        "involve_flags": plaza.involve_flags or [],
        "iteration_note": plaza.iteration_note,
        "status": plaza.status,
        "uploader": uploader,
        "created_at": plaza.inserted_at.isoformat() if plaza.inserted_at else None,
        "updated_at": plaza.updated_at.isoformat() if plaza.updated_at else None,
    }
    if similarity is not None:
        data["similarity"] = similarity
    return data


@router.get("")
async def list_plaza(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """分页列出对当前角色可见的已发布广场 Skill（一般用户不见涉库/涉服务器项 + 黑名单过滤）。

    admin 附带已停用（DISABLED）项（``include_disabled``）供停用现状展示与追溯；其余角色仅 PUBLISHED。
    """
    role_code = current_user.get("role_code")
    blocked = await load_blocked_plaza_ids(db, current_user.get("id"))
    visible = await list_visible_plazas(
        db,
        role_code,
        search=search,
        blocked_plaza_ids=blocked,
        include_disabled=role_code == "admin",
    )
    total = len(visible)
    start = (page - 1) * page_size
    page_items = visible[start : start + page_size]
    uploaders = await _uploader_map(db, [p.uploader_id for p in page_items])
    items = [_serialize(p, uploaders.get(p.uploader_id) if p.uploader_id else None) for p in page_items]
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.get("/search")
async def search_plaza(
    q: str,
    top_k: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """广场语义搜索（F-33）：在角色可见候选内按向量/关键词相似度降序返回（含 similarity 分值）。"""
    role_code = current_user.get("role_code")
    blocked = await load_blocked_plaza_ids(db, current_user.get("id"))
    results = await search_visible_plazas(db, role_code, q, blocked_plaza_ids=blocked, top_k=top_k)
    # 补分享者展示信息（search_visible_plazas 只返回轻量结构）
    plaza_ids = [r["plaza_id"] for r in results]
    plazas: dict[int, PmcpSkillPlaza] = {}
    if plaza_ids:
        rows = (
            await db.execute(select(PmcpSkillPlaza).where(PmcpSkillPlaza.id.in_(plaza_ids)))
        ).scalars().all()
        plazas = {p.id: p for p in rows}
    uploaders = await _uploader_map(db, [p.uploader_id for p in plazas.values()])
    items = []
    for r in results:
        plaza = plazas.get(r["plaza_id"])
        uploader = uploaders.get(plaza.uploader_id) if plaza and plaza.uploader_id else None
        item = _serialize(plaza, uploader, similarity=r["similarity"]) if plaza is not None else dict(r)
        items.append(item)
    return ResponseBase(data={"query": q, "total": len(items), "items": items})


@router.get("/blocked")
async def list_blocked(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """黑名单清单（F-34）：仅黑名单页可见的已屏蔽广场/个人 Skill（服务端分页，id 倒序）。"""
    items = await list_blocked_skills(db, current_user.get("id"))
    start = (page - 1) * page_size
    return ResponseBase(data={"items": items[start:start + page_size], "total": len(items)})


@router.post("/block")
async def block_plaza_skill(
    body: BlockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """屏蔽广场/个人 Skill（F-34，屏蔽后双端不可见，仅黑名单页可见，可撤销）。"""
    actor = ReviewActor.from_user_dict(current_user)
    try:
        entry = await block_skill(db, actor, plaza_id=body.plaza_id, skill_id=body.skill_id, reason=body.reason)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data={"id": entry.id, "plaza_id": entry.target_plaza_id, "skill_id": entry.target_skill_id})


@router.post("/unblock")
async def unblock_plaza_skill(
    body: UnblockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """撤销屏蔽（F-34，撤销后恢复双端可见）。"""
    actor = ReviewActor.from_user_dict(current_user)
    try:
        await unblock_skill(db, actor, plaza_id=body.plaza_id, skill_id=body.skill_id)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(message="已撤销屏蔽")


# ==================== merge 工作台（设计定稿④，2026-09-10，均 admin）====================
# 字面路由 /merge/* 必须声明在 /{plaza_id} 之前，避免 "merge" 被当作 plaza_id 路径参数。


async def _get_merge_row(db: AsyncSession, merge_token: str) -> PmcpPlazaMerge:
    row = (
        await db.execute(select(PmcpPlazaMerge).where(PmcpPlazaMerge.merge_token == merge_token))
    ).scalar_one_or_none()
    if row is None:
        raise SkillReviewError("merge_token 不存在", code=CODE_NOT_FOUND)
    return row


@router.post("/merge/build")
async def merge_build(
    body: MergeBuildRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """merge 工作台 build（仅 admin）：个人 Skill(们) 与广场基线文件级并集 → 临时包 + 冲突清单。"""
    from platform_mcp.skills.merge_service import build_merge_version

    actor = ReviewActor.from_user_dict(_admin)
    try:
        result = await build_merge_version(
            db,
            plaza_id=body.plaza_id,
            source_skill_ids=body.source_skill_ids,
            actor=actor,
            base_version=body.base_version,
            target_version=body.target_version,
            comment=body.comment,
        )
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data=result)


@router.get("/merge/{merge_token}")
async def merge_detail(
    merge_token: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """merge 工作台详情（仅 admin）：临时包状态 / 源清单 / 冲突清单 / 审计摘要。"""
    try:
        row = await _get_merge_row(db, merge_token)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data=serialize_merge(row))


@router.get("/merge/{merge_token}/files")
async def merge_files(
    merge_token: str,
    path: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """merge 工作台文件浏览（仅 admin）：无 path 返回临时包文件清单；带 path 返回单文件内容预览。"""
    from platform_mcp.skills.ecosystem.plaza_tools import _read_package_file

    try:
        row = await _get_merge_row(db, merge_token)
        if row.status != "BUILT":
            raise SkillReviewError(f"该合并任务已终结（status={row.status}）", code=CODE_INVALID_STATE)
        root = Path(row.snapshot_path or "")
        if not root.is_dir():
            raise SkillReviewError("合并临时包目录缺失，请重新 build", code=CODE_INVALID_STATE)
        if path:
            payload = _read_package_file(str(root), path.strip().replace("\\", "/"))
            return ResponseBase(data={"merge_token": merge_token, "path": path, **payload})
        files = [
            {"path": f.relative_to(root).as_posix(), "size": f.stat().st_size}
            for f in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix())
            if f.is_file()
        ]
        return ResponseBase(data={"merge_token": merge_token, "total": len(files), "files": files})
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)


@router.post("/merge/{merge_token}/publish")
async def merge_publish(
    merge_token: str,
    body: MergePublishRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """merge 工作台发布/丢弃（仅 admin）：publish 应用裁决+终审+全链路发布；discard 丢弃临时包。"""
    from platform_mcp.skills.merge_service import publish_merge_version

    actor = ReviewActor.from_user_dict(_admin)
    try:
        result = await publish_merge_version(
            db,
            merge_token=merge_token,
            action=body.action,  # type: ignore[arg-type]
            actor=actor,
            resolutions=body.resolutions,
            target_version=body.target_version,
            comment=body.comment,
        )
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(data=result)


@router.post("/{plaza_id}/copy")
async def copy_to_my(
    plaza_id: int,
    body: PlazaCopyRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """"添加至我的"/复制到个人库（add_skill_to_my）：广场副本复制为个人 Skill（origin=PLAZA，可直接使用）。

    批次 6.2：skill_code 冲突返回 code=10006 + data（conflict_skill_id/conflict_code/overwrite_available），
    前端据此弹「覆盖本地副本 / 更名后重试」二选一，重传 conflict_resolution=overwrite 或 retry+new_code。
    """
    actor = ReviewActor.from_user_dict(current_user)
    try:
        skill = await copy_plaza_to_personal(
            db,
            plaza_id,
            actor,
            conflict_resolution=body.conflict_resolution if body else None,
            new_code=body.new_code if body else None,
        )
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message, data=getattr(exc, "data", None))
    return ResponseBase(data={
        "skill_id": skill.id,
        "skill_code": skill.skill_code,
        "skill_name": skill.skill_name,
        "origin": skill.origin,
        "plaza_id": skill.plaza_id,
        "status": skill.status,
    })


@router.post("/{plaza_id}/disable")
async def disable_plaza(
    plaza_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """停用广场 Skill（仅 admin）：停用后对所有角色 Web + MCP 双端不可见，版本存档与审计保留；幂等。"""
    actor = ReviewActor.from_user_dict(_admin)
    try:
        plaza = await disable_plaza_skill(db, plaza_id, actor)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(message="已停用", data={"plaza_id": plaza.id, "status": plaza.status})


@router.get("/{plaza_id}")
async def get_plaza_detail(
    plaza_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """广场 Skill 详情（可见性校验：非 PUBLISHED / 一般用户涉库项返回 10004）。"""
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None:
        return ResponseBase(code=10002, message="广场 Skill 不存在")
    role_code = current_user.get("role_code")
    if not plaza_visible_to_role(plaza.status, plaza.involve_flags, role_code):
        return ResponseBase(code=10004, message="无权查看该广场 Skill")
    blocked = await load_blocked_plaza_ids(db, current_user.get("id"))
    uploader = None
    if plaza.uploader_id:
        uploaders = await _uploader_map(db, [plaza.uploader_id])
        uploader = uploaders.get(plaza.uploader_id)
    data = _serialize(plaza, uploader)
    data["blocked"] = plaza.id in blocked
    return ResponseBase(data=data)


@router.get("/{plaza_id}/readme")
async def get_plaza_readme(
    plaza_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """广场 Skill 双语 README（镜像 MCP ``get_skill_readme`` plaza 路径，架构 §19.5.3 / §19.5.6）。

    可见性校验同详情端点（非 PUBLISHED / 一般用户涉库项返回 10004）；命中包内已存 README.md 优先，
    缺失时按元数据模板兜底生成。返回 ``readme_zh`` / ``readme_en`` 由前端按当前 locale 选取
    （与 ``/skills/{id}/versions`` 端点模式一致）。
    """
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None:
        return ResponseBase(code=10002, message="广场 Skill 不存在")
    role_code = current_user.get("role_code")
    if not plaza_visible_to_role(plaza.status, plaza.involve_flags, role_code):
        return ResponseBase(code=10004, message="无权查看该广场 Skill")
    readme_zh, readme_en = generate_bilingual_readme(
        plaza.skill_name, plaza.description, plaza.source_path or "", plaza.version or "0.1.0"
    )
    return ResponseBase(data={
        "plaza_id": plaza.id,
        "skill_code": plaza.skill_code,
        "skill_name": plaza.skill_name,
        "readme_zh": readme_zh,
        "readme_en": readme_en,
    })


@router.get("/{plaza_id}/versions")
async def get_plaza_versions(
    plaza_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """广场版本列表（可见者只读，id 倒序）：版本 / 来源提交人版本 / 文件数 / 审计结论 / 归档时间。

    回滚操作（批次4）走独立 admin 端点；此处仅只读展示。
    """
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None:
        return ResponseBase(code=10002, message="广场 Skill 不存在")
    role_code = current_user.get("role_code")
    if not plaza_visible_to_role(plaza.status, plaza.involve_flags, role_code):
        return ResponseBase(code=10004, message="无权查看该广场 Skill")
    versions = await list_plaza_versions(db, plaza_id)
    return ResponseBase(data={"plaza_id": plaza_id, "current_version": plaza.version, "versions": versions})


@router.post("/{plaza_id}/versions/{version}/rollback")
async def rollback_plaza(
    plaza_id: int,
    version: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """广场版本回退（仅 admin，设计定稿⑦）：归档快照复制回生效目录，不新建版本行。

    回滚即版本变更：持有者副本批量标记迭代（无邮件），README 迭代段落以
    「当前生效版本 ≠ 最新归档版」尾行呈现；与 ``scripts/_rollback_plaza_version.py``
    委托同一服务编排。
    """
    actor = ReviewActor.from_user_dict(_admin)
    try:
        result = await rollback_plaza_version(db, plaza_id, version, actor)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
    return ResponseBase(message="已回退", data=result)
