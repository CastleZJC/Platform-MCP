"""用户管理 API"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.api_key_models import PmcpApiKey
from platform_mcp.auth.api_key_service import generate_api_key
from platform_mcp.auth.middleware import require_admin
from platform_mcp.auth.models import PmcpRole, PmcpUser, PmcpUserRole
from platform_mcp.auth.service import hash_password
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase

router = APIRouter(prefix="/users", tags=["用户管理"])


class UserCreateRequest(BaseModel):
    username: str
    password: str
    nickname: str | None = None
    email: str | None = None
    role_code: str = "developer"


class UserUpdateRequest(BaseModel):
    nickname: str | None = None
    role_code: str | None = None


class StatusUpdateRequest(BaseModel):
    status: int


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("")
async def list_users(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    role: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    query = select(PmcpUser)
    count_query = select(func.count()).select_from(PmcpUser)
    if search:
        clause = PmcpUser.username.ilike(f"%{search}%") | PmcpUser.nickname.ilike(f"%{search}%")
        query = query.where(clause)
        count_query = count_query.where(clause)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpUser.id)
    result = await db.execute(query)
    users = result.scalars().all()

    items = []
    for u in users:
        role_res = await db.execute(
            select(PmcpRole.role_code)
            .join(PmcpUserRole, PmcpUserRole.role_id == PmcpRole.id)
            .where(PmcpUserRole.user_id == u.id)
        )
        role_code = role_res.scalar_one_or_none() or "developer"
        # 查活跃的 API Key（取最新一条的 key_prefix）
        key_result = await db.execute(
            select(PmcpApiKey.key_prefix)
            .where(PmcpApiKey.user_id == u.id, PmcpApiKey.status == 1)
            .order_by(PmcpApiKey.inserted_at.desc())
            .limit(1)
        )
        api_key_prefix = key_result.scalar_one_or_none()
        items.append(
            {
                "id": u.id,
                "username": u.username,
                "nickname": u.nickname,
                "email": u.email,
                "role_code": role_code,
                "api_key_prefix": api_key_prefix,
                "status": u.status,
                "created_at": u.inserted_at.isoformat() if u.inserted_at else None,
            }
        )
    return ResponseBase(
        data=PageResult.create(items, total, page, page_size)
    )


@router.post("")
async def create_user(
    body: UserCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    existing = await db.execute(select(PmcpUser).where(PmcpUser.username == body.username))
    if existing.scalar_one_or_none():
        return ResponseBase(code=11002, message="用户名已存在")
    user = PmcpUser(username=body.username, password=hash_password(body.password), nickname=body.nickname)
    user.email = body.email
    db.add(user)
    await db.flush()
    role_res = await db.execute(select(PmcpRole).where(PmcpRole.role_code == body.role_code))
    role = role_res.scalar_one_or_none()
    if role:
        db.add(PmcpUserRole(user_id=user.id, role_id=role.id))
    api_key = await generate_api_key(db, user.id, "初始密钥")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="permission",
        resource_id=str(user.id),
        request_summary=f"创建用户: {user.username}",
        result_status="success",
        extra_data={"created_user": user.username, "role_code": body.role_code, "api_key_generated": True},
        duration_ms=duration_ms,
    )
    return ResponseBase(
        data={
            "user_id": user.id,
            "username": user.username,
            "api_key": api_key,
        },
        message="用户创建成功，请立即保存 API Key",
    )


@router.put("/{user_id}")
async def update_user(
    user_id: int, body: UserUpdateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    user = await db.get(PmcpUser, user_id)
    if not user:
        return ResponseBase(code=11003, message="用户不存在")
    changes = []
    if body.nickname is not None:
        user.nickname = body.nickname
        changes.append(f"nickname={body.nickname}")
    if body.role_code:
        from sqlalchemy import delete as _delete_stmt
        await db.execute(_delete_stmt(PmcpUserRole).where(PmcpUserRole.user_id == user_id))
        role_res = await db.execute(select(PmcpRole).where(PmcpRole.role_code == body.role_code))
        role = role_res.scalar_one_or_none()
        if role:
            db.add(PmcpUserRole(user_id=user_id, role_id=role.id))
        changes.append(f"role_code={body.role_code}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="permission",
        resource_id=str(user_id),
        request_summary=f"更新用户: {user.username}, 变更: {', '.join(changes) if changes else '无'}",
        result_status="success",
        extra_data={"target_user": user.username, "changes": changes},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="用户更新成功")


@router.put("/{user_id}/status")
async def update_user_status(
    user_id: int, body: StatusUpdateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    user = await db.get(PmcpUser, user_id)
    if not user:
        return ResponseBase(code=11003, message="用户不存在")
    old_status = user.status
    user.status = body.status
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="permission",
        resource_id=str(user_id),
        request_summary=f"修改用户状态: {user.username}, {old_status} -> {body.status}",
        result_status="success",
        extra_data={"target_user": user.username, "old_status": old_status, "new_status": body.status},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="状态更新成功")


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    user = await db.get(PmcpUser, user_id)
    if not user:
        return ResponseBase(code=11003, message="用户不存在")
    user.password = hash_password(body.new_password)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="permission",
        resource_id=str(user_id),
        request_summary=f"重置用户密码: {user.username}",
        result_status="success",
        extra_data={"target_user": user.username},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="密码重置成功")
