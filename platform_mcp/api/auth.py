"""登录/登出接口"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user
from platform_mcp.auth.models import PmcpUser
from platform_mcp.auth.schemas import LoginRequest
from platform_mcp.auth.service import authenticate_user
from platform_mcp.auth.session import session_manager
from platform_mcp.common.database import get_db
from platform_mcp.common.response import ResponseBase

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    import time
    start = time.monotonic()
    user = await authenticate_user(body.username, body.password)
    duration_ms = int((time.monotonic() - start) * 1000)
    if user is None:
        await write_audit_log(
            operator=body.username,
            resource_type="auth",
            request_summary="用户登录失败",
            result_status="error",
            error_code="11001",
            error_message="用户名或密码错误",
            duration_ms=duration_ms,
        )
        return ResponseBase(code=11001, message="用户名或密码错误")
    from platform_mcp.common.runtime_config import runtime_config

    timeout_minutes = int(await runtime_config.get("session.timeout_minutes"))
    default_locale = str(await runtime_config.get("sys.default_locale"))
    # 个人每页条数：未设置时回退系统默认（与 locale 同模式；/auth/me 实时读库）
    user["page_size"] = user.get("page_size") or int(await runtime_config.get("sys.default_page_size"))
    session_id = session_manager.create(
        user_id=user["id"], username=user["username"], nickname=user["nickname"], role_code=user["role_code"],
        status=user["status"], email=user.get("email"),
        locale=user.get("locale") or default_locale, ttl_seconds=timeout_minutes * 60,
    )
    response.set_cookie(
        "session_id", session_id, httponly=True, max_age=timeout_minutes * 60, samesite="lax"
    )
    await write_audit_log(
        operator=user["username"],
        resource_type="auth",
        request_summary="用户登录成功",
        result_status="success",
        duration_ms=duration_ms,
        extra_data={"role_code": user["role_code"]},
    )
    return ResponseBase(data=user)


@router.post("/logout")
async def logout(request: Request, response: Response):
    import time
    start = time.monotonic()
    session_id = request.cookies.get("session_id")
    operator = "anonymous"
    if session_id:
        info = session_manager.get(session_id)
        if info is not None:
            operator = info.username
        session_manager.delete(session_id)
    response.delete_cookie("session_id")
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=operator,
        resource_type="auth",
        request_summary="用户退出登录",
        result_status="success",
        duration_ms=duration_ms,
    )
    return ResponseBase(message="已退出登录")


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 个人偏好实时读库：语言/每页条数变更后无需重新登录（刷新 /auth/me 即最新）
    user = await db.get(PmcpUser, current_user["id"])
    if user is not None:
        if isinstance(user.locale, str) and user.locale:
            current_user["locale"] = user.locale
        if isinstance(user.page_size, int) and not isinstance(user.page_size, bool):
            current_user["page_size"] = user.page_size
    return ResponseBase(data=current_user)
