"""API Key 管理 API"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, update

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.api_key_models import PmcpApiKey
from platform_mcp.auth.api_key_service import (
    generate_api_key,
    get_full_key_by_user,
    list_user_keys,
    regenerate_api_key,
    revoke_api_key,
)
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.exceptions import AuthError
from platform_mcp.common.response import ResponseBase

router = APIRouter(prefix="/api-keys", tags=["API Key 管理"])


class CreateKeyRequest(BaseModel):
    description: str | None = None


@router.get("")
async def list_keys(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出当前用户的所有 API Key（仅 key_prefix 掩码，不含完整 Key）。"""
    user_id = current_user["id"]
    keys = await list_user_keys(db, user_id)
    return ResponseBase(data=keys)


@router.post("")
async def create_key(
    body: CreateKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """生成新 API Key，返回完整 Key（仅此一次，后续不可查询）。"""
    import time
    start = time.monotonic()
    user_id = current_user["id"]
    raw_key = await generate_api_key(db, user_id, body.description)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=current_user["username"],
        resource_type="permission",
        resource_id=str(user_id),
        request_summary="生成新 API Key",
        result_status="success",
        extra_data={"description": body.description, "key_prefix": raw_key[:10]},
        duration_ms=duration_ms,
    )
    return ResponseBase(
        data={"key": raw_key, "key_prefix": raw_key[:10] + "****" + raw_key[-4:]},
        message="API Key 已生成，请立即保存（后续不可查看完整 Key）",
    )


@router.delete("/{key_id}")
async def delete_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """撤销 API Key。"""
    import time
    start = time.monotonic()
    ok = await revoke_api_key(db, key_id, current_user["id"])
    if not ok:
        return ResponseBase(code=1, message="Key 不存在或已撤销")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=current_user["username"],
        resource_type="permission",
        resource_id=str(key_id),
        request_summary=f"撤销 API Key: key_id={key_id}",
        result_status="success",
        extra_data={"key_id": key_id},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="API Key 已撤销")


@router.post("/{key_id}/regenerate")
async def refresh_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """重置 API Key（撤销旧 Key + 生成新 Key）。"""
    import time
    start = time.monotonic()
    new_key = await regenerate_api_key(db, key_id, current_user["id"])
    if new_key is None:
        return ResponseBase(code=1, message="Key 不存在")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=current_user["username"],
        resource_type="permission",
        resource_id=str(key_id),
        request_summary=f"重置 API Key: key_id={key_id}",
        result_status="success",
        extra_data={"key_id": key_id, "new_key_prefix": new_key[:10]},
        duration_ms=duration_ms,
    )
    return ResponseBase(
        data={"key": new_key, "key_prefix": new_key[:10] + "****" + new_key[-4:]},
        message="API Key 已重置，旧 Key 立即失效，请保存新 Key",
    )


@router.post("/reset/{user_id}")
async def admin_reset_user_key(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """Admin 重置指定用户的所有活跃 API Key 并生成新 Key。"""
    import time
    start = time.monotonic()
    # 撤销该用户所有活跃 Key
    await db.execute(
        update(PmcpApiKey).where(
            PmcpApiKey.user_id == user_id, PmcpApiKey.status == 1
        ).values(status=0)
    )
    new_key = await generate_api_key(db, user_id, "管理员重置")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="permission",
        resource_id=str(user_id),
        request_summary=f"管理员重置用户 API Key: user_id={user_id}",
        result_status="success",
        extra_data={"target_user_id": user_id, "key_prefix": new_key[:10]},
        duration_ms=duration_ms,
    )
    return ResponseBase(
        data={"key": new_key, "key_prefix": new_key[:10] + "****" + new_key[-4:]},
        message="API Key 已重置",
    )


@router.get("/full/{user_id}")
async def reveal_user_key(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """查看指定用户当前活跃 Key 的明文（self-or-admin）。
    - admin 可查看任意 user_id
    - 普通用户只能查看自己的 user_id
    若用户无活跃 Key 或活跃 Key 在 key_encrypted 列引入前生成（key_encrypted 为 NULL），
    返回 code=1 + 提示需 reset。
    """
    import time
    start = time.monotonic()
    if current_user["role_code"] != "admin" and current_user["id"] != user_id:
        raise AuthError("权限不足：只能查看自己的 API Key")
    full = await get_full_key_by_user(db, user_id)
    if full is None:
        return ResponseBase(
            code=1,
            message="该用户当前无活跃 Key 或 Key 在新机制前生成（无法 reveal 明文），请点击重置生成新 Key",
        )
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=current_user["username"],
        resource_type="permission",
        resource_id=str(user_id),
        request_summary=f"查看用户 API Key 明文: user_id={user_id}",
        result_status="success",
        extra_data={"target_user_id": user_id, "revealed_by": current_user["username"], "is_admin": current_user["role_code"] == "admin"},
        duration_ms=duration_ms,
    )
    return ResponseBase(data={"key": full, "key_prefix": full[:10] + "****" + full[-4:]})
