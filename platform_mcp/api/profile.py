"""个人设置 API"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user
from platform_mcp.auth.models import PmcpRole, PmcpUser, PmcpUserRole
from platform_mcp.auth.service import hash_password, verify_password
from platform_mcp.common.database import get_db
from platform_mcp.common.response import ResponseBase

router = APIRouter(prefix="/profile", tags=["个人设置"])


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = None
    email: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.get("")
async def get_profile(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.get(PmcpUser, current_user["id"])
    if not user:
        return ResponseBase(code=11003, message="用户不存在")
    role_result = await db.execute(
        select(PmcpRole.role_code)
        .join(PmcpUserRole, PmcpUserRole.role_id == PmcpRole.id)
        .where(PmcpUserRole.user_id == user.id)
    )
    role_row = role_result.scalar_one_or_none()
    return ResponseBase(
        data={
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "email": user.email,
            "status": user.status,
            "role_code": role_row,
            "created_at": user.inserted_at.isoformat() if user.inserted_at else None,
        }
    )


@router.put("")
async def update_profile(
    body: ProfileUpdateRequest, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    import time
    start = time.monotonic()
    user = await db.get(PmcpUser, current_user["id"])
    if not user:
        return ResponseBase(code=11003, message="用户不存在")
    changes = []
    if body.nickname is not None:
        user.nickname = body.nickname
        changes.append(f"nickname={body.nickname}")
    if body.email is not None:
        user.email = body.email
        changes.append(f"email={body.email}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=current_user["username"],
        resource_type="permission",
        resource_id=str(current_user["id"]),
        request_summary=f"更新个人资料: {', '.join(changes) if changes else '无'}",
        result_status="success",
        extra_data={"changes": changes},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="更新成功")


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    import time
    start = time.monotonic()
    user = await db.get(PmcpUser, current_user["id"])
    if not user:
        return ResponseBase(code=11003, message="用户不存在")
    if not verify_password(body.old_password, user.password):
        await write_audit_log(
            operator=current_user["username"],
            resource_type="permission",
            resource_id=str(current_user["id"]),
            request_summary=f"修改密码失败：当前密码错误",
            result_status="error",
            error_code="11004",
            error_message="当前密码错误",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return ResponseBase(code=11004, message="当前密码错误")
    user.password = hash_password(body.new_password)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=current_user["username"],
        resource_type="permission",
        resource_id=str(current_user["id"]),
        request_summary="修改个人密码",
        result_status="success",
        duration_ms=duration_ms,
    )
    return ResponseBase(message="密码修改成功")
