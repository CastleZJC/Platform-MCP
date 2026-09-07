"""认证业务逻辑"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.auth.models import PmcpRole, PmcpUser, PmcpUserRole
from platform_mcp.common import database as _db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 启动期强制选定 bcrypt 包作为 backend；缺失时 fail-fast 给出明确提示，
# 避免登录期才报 "no backends available"。
# passlib 的 cryptography 后端不实现 bcrypt 算法，验证 $2b$ 哈希必须装 bcrypt 包。
try:
    pwd_context.hash("__backend_probe__")
except Exception as _backend_err:  # pragma: no cover - 启动期一次性校验
    if "backend" in str(_backend_err).lower():
        raise RuntimeError(
            "密码哈希 backend 不可用：passlib 验证 $2b$ bcrypt 哈希必须依赖 bcrypt 包。\n"
            "请执行：pip install bcrypt==4.2.0"
        ) from _backend_err
    raise

# V3.0 M5（F-37 user_mgmt 捕捉点功能前提）：连续登录失败锁定——5 次失败锁 15 分钟；
# 锁定期内直接拒绝（不增计数、不向调用方泄露锁定状态）；成功登录清零。
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15


def hash_password(password: str) -> str:
    return str(pwd_context.hash(password))


def verify_password(plain: str, hashed: str) -> bool:
    return bool(pwd_context.verify(plain, hashed))


async def get_live_locale(db: AsyncSession, user_id: int) -> str | None:
    """用户语言偏好实时值（V3.0：个人设置保存即生效，后端生成内容绕过登录快照实时读库）。"""
    return (
        await db.execute(select(PmcpUser.locale).where(PmcpUser.id == user_id))
    ).scalar_one_or_none()


async def authenticate_user(username: str, password: str) -> dict | None:
    now = datetime.now(timezone.utc)
    async with _db.get_session_factory()() as session:
        result = await session.execute(select(PmcpUser).where(PmcpUser.username == username, PmcpUser.status == 1))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        if user.locked_until is not None and user.locked_until > now:
            return None  # 锁定期内：静默拒绝（计数不增，防刷解锁窗口）
        if not verify_password(password, user.password):
            user.failed_attempts = int(user.failed_attempts or 0) + 1
            locked_until = None
            if user.failed_attempts >= LOGIN_MAX_FAILED_ATTEMPTS:
                locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
                user.locked_until = locked_until
                user.failed_attempts = 0  # 锁定即清零：解锁后重新累计
            await session.commit()
            if locked_until is not None:
                logger.warning(
                    "用户 {} 连续 {} 次登录失败，锁定至 {}",
                    username, LOGIN_MAX_FAILED_ATTEMPTS, locked_until,
                )
                await _notify_lockout(username, locked_until)
            return None
        if user.failed_attempts or user.locked_until is not None:
            user.failed_attempts = 0
            user.locked_until = None
            await session.commit()
        role_result = await session.execute(
            select(PmcpRole.role_code)
            .join(PmcpUserRole, PmcpUserRole.role_id == PmcpRole.id)
            .where(PmcpUserRole.user_id == user.id)
        )
        role_code = role_result.scalar_one_or_none() or "developer"
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "email": user.email,
            "locale": user.locale,
            "page_size": user.page_size,
            "role_code": role_code,
            "status": user.status,
        }


async def _notify_lockout(username: str, locked_until: datetime) -> None:
    """连续登录失败锁定 → user_mgmt 邮件组 ∪ 相关用户本人（F-37，outbox 落库不发送）。"""
    from platform_mcp.notify.service import dispatch_notification

    extra: list[tuple[int | None, str]] | None = None
    async with _db.get_session_factory()() as session:
        row = (
            await session.execute(
                select(PmcpUser.id, PmcpUser.email).where(PmcpUser.username == username)
            )
        ).first()
    if row is not None and row.email:
        extra = [(row.id, row.email)]
    await dispatch_notification(
        "user_mgmt",
        {
            "user": username,
            "resource": username,
            "action": "连续登录失败锁定",
            "reason": f"连续 {LOGIN_MAX_FAILED_ATTEMPTS} 次登录失败，锁定至 "
                      f"{locked_until.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        },
        source="lockout",
        extra_recipients=extra,
        operator=username,
    )
