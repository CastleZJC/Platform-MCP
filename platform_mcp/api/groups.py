"""分组管理 API — V3.0 统一组（组员+数据源+服务器三类成员多对多）

对应 migration 005 统一组模型；权限同用户管理（仅 admin，技术架构说明文档 §19.5.4）。
审计 resource_type="group"（前端 AuditPage 标签"分组管理"）。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.datasource.models import PmcpDatasource
from platform_mcp.group.models import (
    PmcpGroup,
    PmcpGroupDatasource,
    PmcpGroupServer,
    PmcpGroupUser,
)
from platform_mcp.server.models import PmcpServer
from platform_mcp.auth.models import PmcpUser

router = APIRouter(prefix="/groups", tags=["分组管理"])

_GROUP_NOT_FOUND = 14001
_GROUP_DUPLICATE = 14003
_GROUP_BAD_RESOURCE = 14004


# ==================== Pydantic 请求模型 ====================

class GroupCreateRequest(BaseModel):
    group_name: str
    description: str | None = None
    env_code: str


class GroupUpdateRequest(BaseModel):
    group_name: str | None = None
    description: str | None = None
    env_code: str | None = None
    status: int | None = None


class GroupMembersSetRequest(BaseModel):
    """组成员设置请求 — 按资源类型覆盖式设置"""
    resource: str  # "user" / "datasource" / "server"
    ids: list[int]


class UserGroupsSetRequest(BaseModel):
    """用户所属组设置请求 — 覆盖式设置用户全部组"""
    group_ids: list[int]


def _member_model(resource: str):
    mapping = {"user": PmcpGroupUser, "datasource": PmcpGroupDatasource, "server": PmcpGroupServer}
    if resource not in mapping:
        raise ValueError(f"未知资源类型: {resource}")
    return mapping[resource]


async def _member_counts(db: AsyncSession, group_ids: list[int]) -> dict[int, dict[str, int]]:
    """统计一组 id 的三类成员数量（供列表展示）"""
    counts: dict[int, dict[str, int]] = {gid: {"user": 0, "datasource": 0, "server": 0} for gid in group_ids}
    if not group_ids:
        return counts
    for name, model in (("user", PmcpGroupUser), ("datasource", PmcpGroupDatasource), ("server", PmcpGroupServer)):
        rows = (await db.execute(
            select(model.group_id, func.count()).where(model.group_id.in_(group_ids)).group_by(model.group_id)
        )).all()
        for gid, cnt in rows:
            counts[gid][name] = cnt
    return counts


# ==================== 行级资源-组关联（数据源/服务器页"新增分组"承接） ====================

class ResourceMembershipRequest(BaseModel):
    """设置单个数据源/服务器所属的全部组（diff 增删，不触碰各组其他成员）"""
    resource: str  # "datasource" / "server"
    resource_id: int
    group_ids: list[int]


@router.get("/resource-membership")
async def get_resource_membership(
    resource: str,
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """查询单个数据源/服务器当前所属的组 id 列表"""
    try:
        model = _member_model(resource)
    except ValueError:
        return ResponseBase(code=_GROUP_BAD_RESOURCE, message=f"非法资源类型: {resource}")
    res_col = {"user": "user_id", "datasource": "datasource_id", "server": "server_id"}[resource]
    rows = (await db.execute(
        select(model.group_id).where(getattr(model, res_col) == resource_id)
    )).scalars().all()
    return ResponseBase(data={"group_ids": sorted(set(rows))})


@router.put("/resource-membership")
async def set_resource_membership(
    body: ResourceMembershipRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """幂等设置单个数据源/服务器的所属组：仅对差集做 INSERT/DELETE（与整组覆盖式 PUT /{id}/members 互补）"""
    try:
        model = _member_model(body.resource)
    except ValueError:
        return ResponseBase(code=_GROUP_BAD_RESOURCE, message=f"非法资源类型: {body.resource}")
    start = time.monotonic()
    res_col = {"user": "user_id", "datasource": "datasource_id", "server": "server_id"}[body.resource]
    col = getattr(model, res_col)
    current = set(
        (await db.execute(select(model.group_id).where(col == body.resource_id))).scalars().all()
    )
    target = set(body.group_ids)
    to_add = target - current
    to_remove = current - target
    if to_remove:
        await db.execute(
            delete(model).where(col == body.resource_id, model.group_id.in_(to_remove))
        )
    for gid in to_add:
        db.add(model(group_id=gid, **{res_col: body.resource_id}, inserted_by=_admin["username"]))
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(body.resource_id),
        request_summary=(
            f"调整{ '数据源' if body.resource == 'datasource' else '服务器'}所属组: "
            f"id={body.resource_id}, +{sorted(to_add)} -{sorted(to_remove)}"
        ),
        result_status="success",
        extra_data={
            "resource": body.resource, "resource_id": body.resource_id,
            "added": sorted(to_add), "removed": sorted(to_remove),
        },
        duration_ms=duration_ms,
    )
    return ResponseBase(message="资源所属组更新成功")


# ==================== 统一组 CRUD ====================

@router.get("")
async def list_groups(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    env_code: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """列出统一组（分页 + 三类成员计数）"""
    query = select(PmcpGroup)
    count_query = select(func.count()).select_from(PmcpGroup)
    if search:
        clause = PmcpGroup.group_name.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    if env_code:
        query, count_query = query.where(PmcpGroup.env_code == env_code), count_query.where(
            PmcpGroup.env_code == env_code
        )
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpGroup.id)
    groups = (await db.execute(query)).scalars().all()
    counts = await _member_counts(db, [g.id for g in groups])
    items = [
        {
            "id": g.id,
            "group_name": g.group_name,
            "description": g.description,
            "env_code": g.env_code,
            "status": g.status,
            "user_count": counts[g.id]["user"],
            "datasource_count": counts[g.id]["datasource"],
            "server_count": counts[g.id]["server"],
            "created_at": g.inserted_at.isoformat() if g.inserted_at else None,
        }
        for g in groups
    ]
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("")
async def create_group(
    body: GroupCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    start = time.monotonic()
    existing = (await db.execute(
        select(PmcpGroup).where(
            (PmcpGroup.group_name == body.group_name) & (PmcpGroup.env_code == body.env_code)
        )
    )).scalar_one_or_none()
    if existing:
        return ResponseBase(code=_GROUP_DUPLICATE, message=f"组已存在: {body.env_code}/{body.group_name}")
    group = PmcpGroup(**body.model_dump(), inserted_by=_admin["username"])
    db.add(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(group.id),
        request_summary=f"创建组: {group.group_name}", result_status="success",
        extra_data={"group_name": group.group_name, "env_code": group.env_code}, duration_ms=duration_ms,
    )
    return ResponseBase(data={"id": group.id, "group_name": group.group_name}, message="组创建成功")


@router.put("/{group_id}")
async def update_group(
    group_id: int, body: GroupUpdateRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    start = time.monotonic()
    group = await db.get(PmcpGroup, group_id)
    if not group:
        return ResponseBase(code=_GROUP_NOT_FOUND, message="组不存在")
    changes = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(group, k, v)
        changes.append(f"{k}={v}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(group_id),
        request_summary=f"更新组: {group.group_name}, 变更: {', '.join(changes)}",
        result_status="success", extra_data={"group_id": group_id, "changes": changes}, duration_ms=duration_ms,
    )
    return ResponseBase(message="组更新成功")


@router.delete("/{group_id}")
async def delete_group(
    group_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    start = time.monotonic()
    group = await db.get(PmcpGroup, group_id)
    if not group:
        return ResponseBase(code=_GROUP_NOT_FOUND, message="组不存在")
    # 三类成员表 FK ondelete=CASCADE 随组删除自动清理
    await db.delete(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(group_id),
        request_summary=f"删除组: {group.group_name}", result_status="success",
        extra_data={"group_id": group_id, "group_name": group.group_name}, duration_ms=duration_ms,
    )
    return ResponseBase(message="组删除成功")


# ==================== 组成员管理（三类） ====================

@router.get("/{group_id}/members")
async def get_group_members(
    group_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """获取组的三类成员清单（组员/数据源/服务器）"""
    group = await db.get(PmcpGroup, group_id)
    if not group:
        return ResponseBase(code=_GROUP_NOT_FOUND, message="组不存在")

    user_rows = (await db.execute(
        select(PmcpUser).join(PmcpGroupUser, PmcpGroupUser.user_id == PmcpUser.id)
        .where(PmcpGroupUser.group_id == group_id)
    )).scalars().all()
    ds_rows = (await db.execute(
        select(PmcpDatasource).join(PmcpGroupDatasource, PmcpGroupDatasource.datasource_id == PmcpDatasource.id)
        .where(PmcpGroupDatasource.group_id == group_id)
    )).scalars().all()
    svr_rows = (await db.execute(
        select(PmcpServer).join(PmcpGroupServer, PmcpGroupServer.server_id == PmcpServer.id)
        .where(PmcpGroupServer.group_id == group_id)
    )).scalars().all()
    return ResponseBase(data={
        "group_id": group_id,
        "group_name": group.group_name,
        "users": [
            {"id": u.id, "username": u.username, "nickname": u.nickname} for u in user_rows
        ],
        "datasources": [
            {"id": d.id, "datasource_code": d.datasource_code, "datasource_name": d.datasource_name,
             "db_type": d.db_type, "env_code": d.env_code}
            for d in ds_rows
        ],
        "servers": [
            {"id": s.id, "server_code": s.server_code, "server_name": s.server_name,
             "host": s.host, "env_code": s.env_code}
            for s in svr_rows
        ],
    })


@router.put("/{group_id}/members")
async def set_group_members(
    group_id: int, body: GroupMembersSetRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """按资源类型覆盖式设置组成员"""
    try:
        model = _member_model(body.resource)
    except ValueError:
        return ResponseBase(code=_GROUP_BAD_RESOURCE, message=f"非法资源类型: {body.resource}")
    start = time.monotonic()
    group = await db.get(PmcpGroup, group_id)
    if not group:
        return ResponseBase(code=_GROUP_NOT_FOUND, message="组不存在")
    await db.execute(delete(model).where(model.group_id == group_id))
    res_col = {"user": "user_id", "datasource": "datasource_id", "server": "server_id"}[body.resource]
    for rid in body.ids:
        db.add(model(group_id=group_id, **{res_col: rid}, inserted_by=_admin["username"]))
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(group_id),
        request_summary=f"设置组成员[{body.resource}]: {group.group_name}, 数量: {len(body.ids)}",
        result_status="success",
        extra_data={"group_id": group_id, "resource": body.resource, "ids": body.ids},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="组成员设置成功")




@router.get("/users/{user_id}")
async def get_user_groups(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """获取用户所属组 id 列表"""
    rows = (await db.execute(
        select(PmcpGroupUser.group_id).where(PmcpGroupUser.user_id == user_id)
    )).scalars().all()
    return ResponseBase(data={"group_ids": list(rows)})


@router.put("/users/{user_id}")
async def assign_user_groups(
    user_id: int, body: UserGroupsSetRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """覆盖式设置用户全部所属组"""
    start = time.monotonic()
    await db.execute(delete(PmcpGroupUser).where(PmcpGroupUser.user_id == user_id))
    for gid in body.group_ids:
        db.add(PmcpGroupUser(user_id=user_id, group_id=gid, inserted_by=_admin["username"]))
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(user_id),
        request_summary=f"设置用户所属组: user_id={user_id}, 组数={len(body.group_ids)}",
        result_status="success",
        extra_data={"user_id": user_id, "group_ids": body.group_ids}, duration_ms=duration_ms,
    )
    return ResponseBase(message="用户所属组更新成功")
