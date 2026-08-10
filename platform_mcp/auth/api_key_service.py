"""API Key 服务 — 生成、校验、管理"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.auth.api_key_models import PmcpApiKey
from platform_mcp.auth.models import PmcpRole, PmcpUser, PmcpUserRole
from platform_mcp.datasource.manager import _get_crypto_utils

KEY_PREFIX = "pmcp_"


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_raw_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def _key_prefix(key: str) -> str:
    return key[:10]


async def generate_api_key(db: AsyncSession, user_id: int, description: str | None = None) -> str:
    """生成新 API Key，SHA-256 哈希存储，AES 加密明文存储（admin reveal 用），返回完整 Key（仅此一次）。"""
    raw = _generate_raw_key()
    crypto = _get_crypto_utils()
    record = PmcpApiKey(
        user_id=user_id,
        key_hash=_hash_key(raw),
        key_prefix=_key_prefix(raw),
        key_encrypted=crypto.encrypt(raw),
        description=description,
        status=1,
    )
    db.add(record)
    await db.flush()
    return raw


async def validate_api_key(db: AsyncSession, key_string: str) -> dict | None:
    """校验 API Key，返回用户身份信息或 None。

    返回字段：user_id, username, nickname, role_code
    """
    if not key_string or not key_string.startswith(KEY_PREFIX):
        return None
    key_hash = _hash_key(key_string)
    result = await db.execute(
        select(PmcpApiKey).where(PmcpApiKey.key_hash == key_hash, PmcpApiKey.status == 1)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None
    # 查用户 + 角色
    user_result = await db.execute(
        select(PmcpUser).where(PmcpUser.id == api_key.user_id, PmcpUser.status == 1)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return None
    role_result = await db.execute(
        select(PmcpRole.role_code)
        .join(PmcpUserRole, PmcpUserRole.role_id == PmcpRole.id)
        .where(PmcpUserRole.user_id == user.id)
    )
    role_code = role_result.scalar_one_or_none() or "developer"
    # 更新最后使用时间并显式 commit（外层 _validate_api_key_async 的 async with 不自动 commit）
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "user_id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "role_code": role_code,
    }


async def list_user_keys(db: AsyncSession, user_id: int) -> list[dict]:
    """列出用户的所有 Key（不含完整 Key，仅 key_prefix 识别）。"""
    result = await db.execute(
        select(PmcpApiKey)
        .where(PmcpApiKey.user_id == user_id)
        .order_by(PmcpApiKey.inserted_at.desc())
    )
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "key_prefix": k.key_prefix,
            "description": k.description,
            "status": k.status,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "inserted_at": k.inserted_at.isoformat() if k.inserted_at else None,
        }
        for k in keys
    ]


async def revoke_api_key(db: AsyncSession, key_id: int, user_id: int) -> bool:
    """撤销指定 Key（仅限本人操作）。"""
    result = await db.execute(
        select(PmcpApiKey).where(
            PmcpApiKey.id == key_id, PmcpApiKey.user_id == user_id, PmcpApiKey.status == 1
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        return False
    key.status = 0
    await db.flush()
    return True


async def regenerate_api_key(db: AsyncSession, key_id: int, user_id: int) -> str | None:
    """撤销旧 Key + 生成新 Key，返回新 Key 明文。旧 Key 不存在或已撤销时返回 None。"""
    result = await db.execute(
        select(PmcpApiKey).where(PmcpApiKey.id == key_id, PmcpApiKey.user_id == user_id)
    )
    old = result.scalar_one_or_none()
    if old is None:
        return None
    old.status = 0
    return await generate_api_key(db, user_id, old.description)


async def get_full_key_by_user(db: AsyncSession, user_id: int) -> str | None:
    """admin reveal 用：返回指定用户当前活跃 Key 的明文。
    若用户无活跃 Key 或活跃 Key 在 key_encrypted 列引入前生成（key_encrypted 为 NULL），返回 None。
    """
    result = await db.execute(
        select(PmcpApiKey).where(
            PmcpApiKey.user_id == user_id,
            PmcpApiKey.status == 1,
        ).order_by(PmcpApiKey.inserted_at.desc())
    )
    key = result.scalars().first()
    if key is None or not key.key_encrypted:
        return None
    crypto = _get_crypto_utils()
    return str(crypto.decrypt(key.key_encrypted))
