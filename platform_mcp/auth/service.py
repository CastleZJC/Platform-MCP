"""认证业务逻辑"""

from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy import select

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


def hash_password(password: str) -> str:
    return str(pwd_context.hash(password))


def verify_password(plain: str, hashed: str) -> bool:
    return bool(pwd_context.verify(plain, hashed))


async def authenticate_user(username: str, password: str) -> dict | None:
    async with _db.get_session_factory()() as session:
        result = await session.execute(select(PmcpUser).where(PmcpUser.username == username, PmcpUser.status == 1))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.password):
            return None
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
            "role_code": role_code,
            "status": user.status,
        }
