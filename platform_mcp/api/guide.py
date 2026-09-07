"""MCP 接入指南 API"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.auth.middleware import get_current_user
from platform_mcp.common.database import get_db
from platform_mcp.common.response import ResponseBase
from platform_mcp.config import get_settings
from platform_mcp.i18n import RESOURCES, get_text
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.registry import get_skill_instance as _get_skill_instance
from platform_mcp.review.state_machine import ReviewStatus

router = APIRouter(prefix="/guide", tags=["MCP 接入指南"])


def _localized_description(skill_code: str | None, description: str | None, locale: str | None) -> str:
    """内置 Skill 功能描述按用户语言取值（skill.desc.* 双语字典）；未登记回退 DB 原值。"""
    key = f"skill.desc.{skill_code}" if skill_code else ""
    if key and key in RESOURCES:
        lang = "en-US" if str(locale or "").lower().startswith("en") else "zh-CN"
        return get_text(key, lang)
    return description or ""


@router.get("/config")
async def get_config(_user: dict = Depends(get_current_user)):
    settings = get_settings()
    host = settings.mcp.http_host
    port = settings.mcp.http_port
    path = settings.mcp.http_path
    config = {
        "dev": {
            "description": "本地开发（stdio 模式，仅限本机）",
            "mcpServers": {
                "Platform-MCP": {
                    "command": "python",
                    "args": ["-m", "platform_mcp.mcp_server"],
                    "env": {
                        "PLATFORM_MCP_API_KEY": "<your-api-key>",
                        "PLATFORM_MCP_ENV": settings.env,
                    },
                }
            },
        },
        "prod": {
            "description": "远程服务器（streamable-http 模式）— 部署后请将 <your-server-ip> 替换为实际服务器 IP/域名",
            "mcpServers": {
                "Platform-MCP": {
                    "url": f"http://<your-server-ip>:{port}{path}/",
                    "type": "http",
                    "headers": {
                        "PLATFORM_MCP_API_KEY": "<your-api-key>",
                    },
                }
            },
            "current_runtime": {"host": host, "port": port, "path": path},
        },
    }
    return ResponseBase(data=config)


@router.get("/tools")
async def get_tools(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # V3.0：语言即时生效——实时读 pmcp_user.locale（个人设置保存即变），读库失败回退登录快照
    from platform_mcp.auth.service import get_live_locale

    locale = await get_live_locale(db, user["id"]) or user.get("locale")
    # V3.0 M0 起 pmcp_skill.status 为 varchar 状态机（原 int 1 比较在 PG 直接类型报错）
    result = await db.execute(
        select(PmcpSkill).where(PmcpSkill.status == ReviewStatus.ENABLED).order_by(PmcpSkill.id)
    )
    skills = result.scalars().all()
    data = []
    for s in skills:
        instance = _get_skill_instance(s.skill_code)
        tools = []
        if instance is not None:
            for meta in instance.list_tools():
                tools.append({
                    "tool_name": meta.tool_name,
                    "display_name": meta.display_name,
                    "description": meta.description,
                    "risk_level": meta.risk_level,
                })
        data.append({
            "skill_code": s.skill_code,
            "skill_name": s.skill_name,
            "description": _localized_description(s.skill_code, s.description, locale),
            "register_method": s.register_method,
            "tool_count": len(tools),
            "tools": tools,
        })
    return ResponseBase(data=data)
