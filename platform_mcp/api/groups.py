"""分组管理 API — V3.0 统一组（组员+数据源+服务器三类成员多对多）

对应 migration 005 统一组模型、migration 008 去环境维度（组与环境正交：组只挂资源集合，
环境管控走资源自身 env_code + 角色双项控制）；权限仅 admin（技术架构说明文档 §19.5.4）。
组不提供删除（成员/权限引用多，仅停用）；审计 resource_type="group"。
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
from platform_mcp.auth.models import PmcpRole, PmcpUser, PmcpUserRole

router = APIRouter(prefix="/groups", tags=["分组管理"])

_GROUP_NOT_FOUND = 14001
_GROUP_DUPLICATE = 14003
_GROUP_BAD_RESOURCE = 14004
_GROUP_MEMBER_ROLE = 14005


# ==================== Pydantic 请求模型 ====================

class GroupCreateRequest(BaseModel):
    group_name: str
    description: str | None = None


class GroupUpdateRequest(BaseModel):
    group_name: str | None = None
    description: str | None = None
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


async def _non_dev_member_usernames(db: AsyncSession, user_ids: list[int]) -> list[str]:
    """组员候选角色核查：返回非 developer 角色的用户名清单。

    组过滤仅对 developer 角色生效（admin 直通、一般用户无 db/server 权限，
    见 group/access.py），admin/一般用户入组无权限语义。无角色关联的用户按
    登录口径默认 developer（auth/service.py 同源逻辑）。
    """
    if not user_ids:
        return []
    rows = (await db.execute(
        select(PmcpUser.id, PmcpUser.username, PmcpRole.role_code)
        .outerjoin(PmcpUserRole, PmcpUserRole.user_id == PmcpUser.id)
        .outerjoin(PmcpRole, PmcpRole.id == PmcpUserRole.role_id)
        .where(PmcpUser.id.in_(user_ids))
    )).all()
    return [username for _, username, role in rows if (role or "developer") != "developer"]


async def _member_counts_and_names(
    db: AsyncSession, group_ids: list[int]
) -> tuple[dict[int, dict[str, int]], dict[int, dict[str, list[str]]]]:
    """统计一组 id 的三类成员数量与名称清单（列表展示名单而非纯计数）"""
    counts: dict[int, dict[str, int]] = {gid: {"user": 0, "datasource": 0, "server": 0} for gid in group_ids}
    names: dict[int, dict[str, list[str]]] = {
        gid: {"user": [], "datasource": [], "server": []} for gid in group_ids
    }
    if not group_ids:
        return counts, names
    specs = (
        ("user", PmcpGroupUser, PmcpGroupUser.user_id, PmcpUser, PmcpUser.id, PmcpUser.username),
        ("datasource", PmcpGroupDatasource, PmcpGroupDatasource.datasource_id,
         PmcpDatasource, PmcpDatasource.id, PmcpDatasource.datasource_name),
        ("server", PmcpGroupServer, PmcpGroupServer.server_id, PmcpServer, PmcpServer.id, PmcpServer.server_name),
    )
    for name, model, res_col, res_model, res_pk, label_col in specs:
        rows = (await db.execute(
            select(model.group_id, label_col)
            .join(res_model, res_pk == res_col)
            .where(model.group_id.in_(group_ids))
        )).all()
        for gid, label in rows:
            counts[gid][name] += 1
            names[gid][name].append(label)
    return counts, names


# ==================== 行级资源-组关联（数据源/服务器页“调整分组”承接） ====================

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
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """列出统一组（分页 + 三类成员计数与名单）"""
    query = select(PmcpGroup)
    count_query = select(func.count()).select_from(PmcpGroup)
    if search:
        clause = PmcpGroup.group_name.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpGroup.id)
    groups = (await db.execute(query)).scalars().all()
    counts, names = await _member_counts_and_names(db, [g.id for g in groups])
    items = [
        {
            "id": g.id,
            "group_name": g.group_name,
            "description": g.description,
            "status": g.status,
            "user_count": counts[g.id]["user"],
            "datasource_count": counts[g.id]["datasource"],
            "server_count": counts[g.id]["server"],
            "user_names": names[g.id]["user"],
            "datasource_names": names[g.id]["datasource"],
            "server_names": names[g.id]["server"],
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
        select(PmcpGroup).where(PmcpGroup.group_name == body.group_name)
    )).scalar_one_or_none()
    if existing:
        return ResponseBase(code=_GROUP_DUPLICATE, message=f"组已存在: {body.group_name}")
    group = PmcpGroup(group_name=body.group_name, description=body.description, inserted_by=_admin["username"])
    db.add(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="group", resource_id=str(group.id),
        request_summary=f"创建组: {group.group_name}", result_status="success",
        extra_data={"group_name": group.group_name}, duration_ms=duration_ms,
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
        select(PmcpUser, PmcpRole.role_code)
        .join(PmcpGroupUser, PmcpGroupUser.user_id == PmcpUser.id)
        .outerjoin(PmcpUserRole, PmcpUserRole.user_id == PmcpUser.id)
        .outerjoin(PmcpRole, PmcpRole.id == PmcpUserRole.role_id)
        .where(PmcpGroupUser.group_id == group_id)
    )).all()
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
            {"id": u.id, "username": u.username, "nickname": u.nickname,
             "role_code": role or "developer"}
            for u, role in user_rows
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
    if body.resource == "user":
        # 校验置于覆盖式 delete 之前：拒绝请求不得清空既有组员
        offenders = await _non_dev_member_usernames(db, body.ids)
        if offenders:
            return ResponseBase(
                code=_GROUP_MEMBER_ROLE,
                message=f"组员仅支持 developer 角色用户，以下用户角色不符: {', '.join(offenders)}",
            )
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
    """覆盖式设置用户全部所属组（仅 developer 角色用户涉及分组）"""
    start = time.monotonic()
    role_code = (await db.execute(
        select(PmcpRole.role_code)
        .join(PmcpUserRole, PmcpUserRole.role_id == PmcpRole.id)
        .where(PmcpUserRole.user_id == user_id)
    )).scalar_one_or_none() or "developer"
    if role_code != "developer":
        return ResponseBase(
            code=_GROUP_MEMBER_ROLE,
            message=f"仅 developer 角色用户涉及分组分配: user_id={user_id} 角色 {role_code}",
        )
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
