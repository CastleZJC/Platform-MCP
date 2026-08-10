"""权限中间件"""

from __future__ import annotations

from fastapi import Depends, Request

from platform_mcp.auth.session import session_manager
from platform_mcp.common.exceptions import AuthError


def get_current_user(request: Request) -> dict:
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise AuthError("未登录")
    info = session_manager.get(session_id)
    if info is None:
        raise AuthError("Session 已过期")
    return {
        "id": info.user_id,
        "username": info.username,
        "nickname": info.nickname,
        "role_code": info.role_code,
        "status": info.status,
        "email": info.email,
    }


def require_role(*roles: str):
    def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role_code"] not in roles:
            raise AuthError("权限不足")
        return current_user

    return _check


require_admin = require_role("admin")
