"""API 路由注册"""

from fastapi import FastAPI

from platform_mcp.api.audit import router as audit_router
from platform_mcp.api.auth import router as auth_router
from platform_mcp.api.crypto import router as crypto_router
from platform_mcp.api.datasources import router as datasources_router
from platform_mcp.api.groups import router as groups_router
from platform_mcp.api.servers import router as servers_router
from platform_mcp.api.guide import router as guide_router
from platform_mcp.api.profile import router as profile_router
from platform_mcp.api.skills import router as skills_router
from platform_mcp.api.api_keys import router as api_keys_router
from platform_mcp.api.users import router as users_router
from platform_mcp.api.system_config import router as system_config_router


def register_api_routes(app: FastAPI) -> None:
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(api_keys_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(datasources_router, prefix="/api/v1")
    app.include_router(servers_router, prefix="/api/v1")
    app.include_router(groups_router, prefix="/api/v1")
    app.include_router(skills_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(crypto_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(guide_router, prefix="/api/v1")
    app.include_router(system_config_router, prefix="/api/v1")
