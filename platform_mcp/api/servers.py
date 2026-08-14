"""服务器管理 API — 镜像 api/datasources.py"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.group.models import PmcpServerGroupMember, PmcpUserGroup
from platform_mcp.server.manager import server_manager
from platform_mcp.server.models import PmcpServer

router = APIRouter(prefix="/servers", tags=["服务器管理"])


class ServerCreateRequest(BaseModel):
    server_code: str = Field(min_length=1)
    server_name: str = Field(min_length=1)
    host: str = Field(min_length=1)
    ssh_port: int = 22
    username: str = Field(min_length=1)
    encrypted_password: str | None = None
    encrypted_ssh_key: str | None = None
    env_code: str = Field(min_length=1)
    max_concurrent: int = 3
    command_timeout: int = 300
    allowed_paths: str | None = None       # JSON 数组字符串
    forbidden_paths: str | None = None     # JSON 数组字符串
    remark: str | None = None

    @field_validator("server_code", "server_name", "host", "username", "env_code")
    @classmethod
    def _reject_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("必填字段不能为空白字符")
        return v


class ServerUpdateRequest(BaseModel):
    server_name: str | None = None
    host: str | None = None
    ssh_port: int | None = None
    username: str | None = None
    encrypted_password: str | None = None
    encrypted_ssh_key: str | None = None
    max_concurrent: int | None = None
    command_timeout: int | None = None
    allowed_paths: str | None = None
    forbidden_paths: str | None = None
    remark: str | None = None


class StatusUpdateRequest(BaseModel):
    status: int


def _srv_to_dict(srv: PmcpServer) -> dict:
    return {
        "id": srv.id,
        "server_code": srv.server_code,
        "server_name": srv.server_name,
        "host": srv.host,
        "ssh_port": srv.ssh_port,
        "username": srv.username,
        "env_code": srv.env_code,
        "status": srv.status,
        "max_concurrent": srv.max_concurrent,
        "command_timeout": srv.command_timeout,
        "allowed_paths": srv.allowed_paths,
        "forbidden_paths": srv.forbidden_paths,
        "remark": srv.remark,
        "has_password": bool(srv.encrypted_password),
        "has_ssh_key": bool(srv.encrypted_ssh_key),
        "created_at": srv.inserted_at.isoformat() if srv.inserted_at else None,
    }


@router.get("")
async def list_servers(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    env_code: str | None = None,
    status: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    query = select(PmcpServer)
    count_query = select(func.count()).select_from(PmcpServer)
    if search:
        clause = PmcpServer.server_code.ilike(f"%{search}%") | PmcpServer.server_name.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    if env_code:
        query, count_query = query.where(PmcpServer.env_code == env_code), count_query.where(
            PmcpServer.env_code == env_code
        )
    if status is not None:
        query, count_query = query.where(PmcpServer.status == status), count_query.where(PmcpServer.status == status)
    # developer 角色通过组过滤可见服务器
    if _user["role_code"] == "developer":
        group_ids = [
            r.group_id for r in (await db.execute(
                select(PmcpUserGroup.group_id).where(
                    (PmcpUserGroup.user_id == _user["id"]) & (PmcpUserGroup.group_type == "server")
                )
            )).scalars().all()
        ]
        if group_ids:
            svr_ids = [
                r.server_id for r in (await db.execute(
                    select(PmcpServerGroupMember.server_id).where(
                        PmcpServerGroupMember.group_id.in_(group_ids)
                    )
                )).scalars().all()
            ]
            query, count_query = query.where(PmcpServer.id.in_(svr_ids)), count_query.where(PmcpServer.id.in_(svr_ids))
        else:
            query, count_query = query.where(PmcpServer.id < 0), count_query.where(PmcpServer.id < 0)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpServer.id)
    items = [_srv_to_dict(srv) for srv in (await db.execute(query)).scalars().all()]
    return ResponseBase(
        data=PageResult(
            items=items, total=total, page=page, page_size=page_size, total_pages=(total + page_size - 1) // page_size
        )
    )


@router.post("")
async def create_server(
    body: ServerCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time

    start = time.monotonic()
    existing = await db.execute(select(PmcpServer).where(PmcpServer.server_code == body.server_code))
    if existing.scalar_one_or_none():
        return ResponseBase(code=13001, message="服务器编码已存在")
    if not body.encrypted_password and not body.encrypted_ssh_key:
        return ResponseBase(code=13002, message="必须提供加密密码或加密私钥（至少一项）")
    srv = PmcpServer(**body.model_dump())
    db.add(srv)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="server",
        resource_id=str(srv.id),
        request_summary=f"创建服务器: {srv.server_code}",
        result_status="success",
        extra_data={"server_code": srv.server_code, "host": srv.host, "env_code": srv.env_code},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="服务器创建成功")


@router.put("/{server_id}")
async def update_server(
    server_id: int,
    body: ServerUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    import time

    start = time.monotonic()
    srv = await db.get(PmcpServer, server_id)
    if not srv:
        return ResponseBase(code=13003, message="服务器不存在")
    changes = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(srv, k, v)
        changes.append(f"{k}={'***' if 'password' in k or 'key' in k else v}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="server",
        resource_id=str(server_id),
        request_summary=f"更新服务器: {srv.server_code}, 变更: {', '.join(changes) if changes else '无'}",
        result_status="success",
        extra_data={"server_code": srv.server_code, "changes": changes},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="服务器更新成功")


@router.put("/{server_id}/status")
async def update_server_status(
    server_id: int,
    body: StatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    import time

    start = time.monotonic()
    srv = await db.get(PmcpServer, server_id)
    if not srv:
        return ResponseBase(code=13003, message="服务器不存在")
    old_status = srv.status
    srv.status = body.status
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="server",
        resource_id=str(server_id),
        request_summary=f"修改服务器状态: {srv.server_code}, {old_status} -> {body.status}",
        result_status="success",
        extra_data={"server_code": srv.server_code, "old_status": old_status, "new_status": body.status},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="状态更新成功")


@router.post("/{server_id}/test")
async def test_connection(server_id: int, db: AsyncSession = Depends(get_db), _user: dict = Depends(get_current_user)):
    import time

    start = time.monotonic()
    srv = await db.get(PmcpServer, server_id)
    if not srv:
        return ResponseBase(code=13003, message="服务器不存在")
    result = await server_manager.test_connection(srv.server_code)
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_user["username"],
        resource_type="server",
        resource_id=str(server_id),
        request_summary=f"测试服务器连接: {srv.server_code}",
        result_status="success" if result.get("success") else "error",
        extra_data={
            "server_code": srv.server_code,
            "test_result": result.get("success"),
            "latency_ms": result.get("latency_ms"),
        },
        duration_ms=duration_ms,
    )
    return ResponseBase(data=result)
