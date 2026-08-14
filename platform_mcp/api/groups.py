"""分组管理 API — 数据源组 + 服务器组 CRUD、成员管理、用户-组关联"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.datasource.models import PmcpDatasource
from platform_mcp.group.models import (
    PmcpDatasourceGroup,
    PmcpDatasourceGroupMember,
    PmcpServerGroup,
    PmcpServerGroupMember,
    PmcpUserGroup,
)
from platform_mcp.server.models import PmcpServer

router = APIRouter(prefix="/groups", tags=["分组管理"])


# ==================== Pydantic 请求模型 ====================

class DatasourceGroupCreateRequest(BaseModel):
    group_name: str
    description: str | None = None
    env_code: str


class DatasourceGroupUpdateRequest(BaseModel):
    group_name: str | None = None
    description: str | None = None
    env_code: str | None = None
    status: int | None = None


class ServerGroupCreateRequest(BaseModel):
    group_name: str
    description: str | None = None
    env_code: str


class ServerGroupUpdateRequest(BaseModel):
    group_name: str | None = None
    description: str | None = None
    env_code: str | None = None
    status: int | None = None


class GroupMembersRequest(BaseModel):
    """组成员分配请求 — 设置组成员（覆盖式）"""
    ids: list[int]


class UserGroupAssignRequest(BaseModel):
    """用户-组关联分配请求"""
    group_type: str  # "datasource" or "server"
    group_ids: list[int]


# ==================== 数据源组 CRUD ====================

@router.get("/datasources")
async def list_datasource_groups(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    env_code: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """列出数据源组（dev 仅可看 DEV/UAT 环境）"""
    query = select(PmcpDatasourceGroup)
    count_query = select(func.count()).select_from(PmcpDatasourceGroup)
    if search:
        clause = PmcpDatasourceGroup.group_name.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    if env_code:
        query, count_query = query.where(PmcpDatasourceGroup.env_code == env_code), count_query.where(
            PmcpDatasourceGroup.env_code == env_code
        )
    if _user["role_code"] == "developer":
        dev_clause = PmcpDatasourceGroup.env_code.in_(["DEV", "UAT"])
        query, count_query = query.where(dev_clause), count_query.where(dev_clause)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpDatasourceGroup.id)
    groups = (await db.execute(query)).scalars().all()
    items = [
        {
            "id": g.id,
            "group_name": g.group_name,
            "description": g.description,
            "env_code": g.env_code,
            "status": g.status,
            "created_at": g.inserted_at.isoformat() if g.inserted_at else None,
        }
        for g in groups
    ]
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("/datasources")
async def create_datasource_group(
    body: DatasourceGroupCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    start = time.monotonic()
    group = PmcpDatasourceGroup(**body.model_dump(), inserted_by=_admin["username"])
    db.add(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group.id),
        request_summary=f"创建数据源组: {group.group_name}", result_status="success",
        extra_data={"group_name": group.group_name, "env_code": group.env_code}, duration_ms=duration_ms,
    )
    return ResponseBase(data={"id": group.id, "group_name": group.group_name}, message="数据源组创建成功")


@router.put("/datasources/{group_id}")
async def update_datasource_group(
    group_id: int, body: DatasourceGroupUpdateRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    start = time.monotonic()
    group = await db.get(PmcpDatasourceGroup, group_id)
    if not group:
        return ResponseBase(code=14001, message="数据源组不存在")
    changes = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(group, k, v)
        changes.append(f"{k}={v}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group_id),
        request_summary=f"更新数据源组: {group.group_name}, 变更: {', '.join(changes)}",
        result_status="success", extra_data={"group_id": group_id, "changes": changes}, duration_ms=duration_ms,
    )
    return ResponseBase(message="数据源组更新成功")


@router.delete("/datasources/{group_id}")
async def delete_datasource_group(
    group_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    start = time.monotonic()
    group = await db.get(PmcpDatasourceGroup, group_id)
    if not group:
        return ResponseBase(code=14001, message="数据源组不存在")
    await db.execute(delete(PmcpDatasourceGroupMember).where(PmcpDatasourceGroupMember.group_id == group_id))
    await db.execute(delete(PmcpUserGroup).where(
        (PmcpUserGroup.group_type == "datasource") & (PmcpUserGroup.group_id == group_id)
    ))
    await db.delete(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group_id),
        request_summary=f"删除数据源组: {group.group_name}", result_status="success",
        extra_data={"group_id": group_id, "group_name": group.group_name}, duration_ms=duration_ms,
    )
    return ResponseBase(message="数据源组删除成功")


# ==================== 数据源组成员管理 ====================

@router.get("/datasources/{group_id}/members")
async def list_datasource_group_members(
    group_id: int, db: AsyncSession = Depends(get_db), _user: dict = Depends(get_current_user),
):
    """获取数据源组的成员列表"""
    group = await db.get(PmcpDatasourceGroup, group_id)
    if not group:
        return ResponseBase(code=14001, message="数据源组不存在")
    member_rows = (await db.execute(
        select(PmcpDatasourceGroupMember).where(PmcpDatasourceGroupMember.group_id == group_id)
    )).scalars().all()
    ds_ids = [m.datasource_id for m in member_rows]
    datasources = []
    if ds_ids:
        ds_rows = (await db.execute(select(PmcpDatasource).where(PmcpDatasource.id.in_(ds_ids)))).scalars().all()
        datasources = [
            {"id": ds.id, "datasource_code": ds.datasource_code, "datasource_name": ds.datasource_name, "db_type": ds.db_type, "env_code": ds.env_code}
            for ds in ds_rows
        ]
    return ResponseBase(data={"group_id": group_id, "group_name": group.group_name, "members": datasources})


@router.put("/datasources/{group_id}/members")
async def set_datasource_group_members(
    group_id: int, body: GroupMembersRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """设置数据源组成员（覆盖式）"""
    start = time.monotonic()
    group = await db.get(PmcpDatasourceGroup, group_id)
    if not group:
        return ResponseBase(code=14001, message="数据源组不存在")
    await db.execute(delete(PmcpDatasourceGroupMember).where(PmcpDatasourceGroupMember.group_id == group_id))
    for ds_id in body.ids:
        db.add(PmcpDatasourceGroupMember(group_id=group_id, datasource_id=ds_id))
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group_id),
        request_summary=f"设置数据源组成员: {group.group_name}, 成员数: {len(body.ids)}",
        result_status="success", extra_data={"group_id": group_id, "member_count": len(body.ids)}, duration_ms=duration_ms,
    )
    return ResponseBase(message="数据源组成员设置成功")


# ==================== 服务器组 CRUD ====================

@router.get("/servers")
async def list_server_groups(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    env_code: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """列出服务器组（dev 仅可看 DEV/UAT 环境）"""
    query = select(PmcpServerGroup)
    count_query = select(func.count()).select_from(PmcpServerGroup)
    if search:
        clause = PmcpServerGroup.group_name.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    if env_code:
        query, count_query = query.where(PmcpServerGroup.env_code == env_code), count_query.where(
            PmcpServerGroup.env_code == env_code
        )
    if _user["role_code"] == "developer":
        dev_clause = PmcpServerGroup.env_code.in_(["DEV", "UAT"])
        query, count_query = query.where(dev_clause), count_query.where(dev_clause)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpServerGroup.id)
    groups = (await db.execute(query)).scalars().all()
    items = [
        {
            "id": g.id,
            "group_name": g.group_name,
            "description": g.description,
            "env_code": g.env_code,
            "status": g.status,
            "created_at": g.inserted_at.isoformat() if g.inserted_at else None,
        }
        for g in groups
    ]
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("/servers")
async def create_server_group(
    body: ServerGroupCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    start = time.monotonic()
    group = PmcpServerGroup(**body.model_dump(), inserted_by=_admin["username"])
    db.add(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group.id),
        request_summary=f"创建服务器组: {group.group_name}", result_status="success",
        extra_data={"group_name": group.group_name, "env_code": group.env_code}, duration_ms=duration_ms,
    )
    return ResponseBase(data={"id": group.id, "group_name": group.group_name}, message="服务器组创建成功")


@router.put("/servers/{group_id}")
async def update_server_group(
    group_id: int, body: ServerGroupUpdateRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    start = time.monotonic()
    group = await db.get(PmcpServerGroup, group_id)
    if not group:
        return ResponseBase(code=14002, message="服务器组不存在")
    changes = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(group, k, v)
        changes.append(f"{k}={v}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group_id),
        request_summary=f"更新服务器组: {group.group_name}, 变更: {', '.join(changes)}",
        result_status="success", extra_data={"group_id": group_id, "changes": changes}, duration_ms=duration_ms,
    )
    return ResponseBase(message="服务器组更新成功")


@router.delete("/servers/{group_id}")
async def delete_server_group(
    group_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    start = time.monotonic()
    group = await db.get(PmcpServerGroup, group_id)
    if not group:
        return ResponseBase(code=14002, message="服务器组不存在")
    await db.execute(delete(PmcpServerGroupMember).where(PmcpServerGroupMember.group_id == group_id))
    await db.execute(delete(PmcpUserGroup).where(
        (PmcpUserGroup.group_type == "server") & (PmcpUserGroup.group_id == group_id)
    ))
    await db.delete(group)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group_id),
        request_summary=f"删除服务器组: {group.group_name}", result_status="success",
        extra_data={"group_id": group_id, "group_name": group.group_name}, duration_ms=duration_ms,
    )
    return ResponseBase(message="服务器组删除成功")


# ==================== 服务器组成员管理 ====================

@router.get("/servers/{group_id}/members")
async def list_server_group_members(
    group_id: int, db: AsyncSession = Depends(get_db), _user: dict = Depends(get_current_user),
):
    """获取服务器组的成员列表"""
    group = await db.get(PmcpServerGroup, group_id)
    if not group:
        return ResponseBase(code=14002, message="服务器组不存在")
    member_rows = (await db.execute(
        select(PmcpServerGroupMember).where(PmcpServerGroupMember.group_id == group_id)
    )).scalars().all()
    svr_ids = [m.server_id for m in member_rows]
    servers = []
    if svr_ids:
        svr_rows = (await db.execute(select(PmcpServer).where(PmcpServer.id.in_(svr_ids)))).scalars().all()
        servers = [
            {"id": s.id, "server_code": s.server_code, "server_name": s.server_name, "host": s.host, "env_code": s.env_code}
            for s in svr_rows
        ]
    return ResponseBase(data={"group_id": group_id, "group_name": group.group_name, "members": servers})


@router.put("/servers/{group_id}/members")
async def set_server_group_members(
    group_id: int, body: GroupMembersRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """设置服务器组成员（覆盖式）"""
    start = time.monotonic()
    group = await db.get(PmcpServerGroup, group_id)
    if not group:
        return ResponseBase(code=14002, message="服务器组不存在")
    await db.execute(delete(PmcpServerGroupMember).where(PmcpServerGroupMember.group_id == group_id))
    for svr_id in body.ids:
        db.add(PmcpServerGroupMember(group_id=group_id, server_id=svr_id))
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(group_id),
        request_summary=f"设置服务器组成员: {group.group_name}, 成员数: {len(body.ids)}",
        result_status="success", extra_data={"group_id": group_id, "member_count": len(body.ids)}, duration_ms=duration_ms,
    )
    return ResponseBase(message="服务器组成员设置成功")


# ==================== 用户-组关联 ====================

@router.get("/users/{user_id}")
async def get_user_groups(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """获取用户的组关联"""
    rows = (await db.execute(
        select(PmcpUserGroup).where(PmcpUserGroup.user_id == user_id)
    )).scalars().all()
    result: dict[str, list[int]] = {"datasource_groups": [], "server_groups": []}
    for r in rows:
        if r.group_type == "datasource":
            result["datasource_groups"].append(r.group_id)
        else:
            result["server_groups"].append(r.group_id)
    return ResponseBase(data=result)


@router.put("/users/{user_id}")
async def assign_user_groups(
    user_id: int, body: UserGroupAssignRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """分配用户到组（覆盖式）"""
    start = time.monotonic()
    await db.execute(
        delete(PmcpUserGroup).where(
            (PmcpUserGroup.user_id == user_id) & (PmcpUserGroup.group_type == body.group_type)
        )
    )
    for gid in body.group_ids:
        db.add(PmcpUserGroup(user_id=user_id, group_type=body.group_type, group_id=gid))
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(user_id),
        request_summary=f"分配用户组: user_id={user_id}, type={body.group_type}, 组数={len(body.group_ids)}",
        result_status="success",
        extra_data={"user_id": user_id, "group_type": body.group_type, "group_ids": body.group_ids},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="用户组关联更新成功")