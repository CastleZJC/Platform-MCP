"""Skill 广场公共池 API（V3.0 M3.1 / M3.3，架构 §19.5.3 / §19.5.6，计划 F-23/F-33/需求 1.1.4）

广场（``pmcp_skill_plaza``）为独立于个人库的公共池，本模块提供全角色可见的：

- ``GET /plaza``：分页列出对当前角色可见的已发布广场 Skill（一般用户不见涉库/涉服务器项，F-23；
  admin 附带已停用项供停用现状展示，其余角色仅 PUBLISHED）；
- ``GET /plaza/search``：语义搜索（BGE-M3 / 降级哈希向量 + 关键词兜底，F-33）；
- ``GET /plaza/{plaza_id}``：广场 Skill 详情（可见性校验 + blocked 标记）；
- ``GET /plaza/{plaza_id}/readme``：广场 Skill 双语 README（镜像 MCP ``get_skill_readme`` plaza 路径）；
- ``POST /plaza/{plaza_id}/disable``：停用广场 Skill（仅 admin，停用后双端不可见，幂等）。

可见性判定统一委托 :mod:`platform_mcp.skills.plaza`（``plaza_visible_to_role`` / ``list_visible_plazas``），
与 MCP ``search_skills`` 双端共用同一过滤口径，避免 Web 侧装饰性放行。黑名单（F-34）屏蔽集合由
``load_blocked_plaza_ids`` 读侧加载并传入过滤（写侧 block/unblock 端点见 M3.4）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.auth.models import PmcpUser
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.review.service import ReviewActor, SkillReviewError
from platform_mcp.skills.models import PmcpSkillPlaza
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


@router.post("/{plaza_id}/copy")
async def copy_to_my(
    plaza_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """"添加至我的"/复制到个人库（add_skill_to_my）：广场副本复制为个人 Skill（origin=PLAZA，可直接使用）。"""
    actor = ReviewActor.from_user_dict(current_user)
    try:
        skill = await copy_plaza_to_personal(db, plaza_id, actor)
    except SkillReviewError as exc:
        return ResponseBase(code=exc.error_code, message=exc.message)
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
