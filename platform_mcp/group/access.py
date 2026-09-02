"""统一组资源可见性助手 — Web API 与 MCP 双入口共用的组过滤判定（技术架构说明文档 §19.5.4）

返回值语义：
- None  = 不限（admin 直通）
- []    = 无任何可访问对象（无组 dev / 一般用户）
- [ids] = 资源 id 白名单（仅所属启用组内对象）
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.group.models import PmcpGroup, PmcpGroupDatasource, PmcpGroupServer, PmcpGroupUser

_VALID_RESOURCES = {"datasource", "server"}


async def accessible_resource_ids(
    db: AsyncSession, *, user_id: int, role_code: str, resource: str
) -> list[int] | None:
    if resource not in _VALID_RESOURCES:
        raise ValueError(f"未知资源类型: {resource}")
    if role_code == "admin":
        return None
    if role_code == "user":
        # 一般用户无 database/server 权限（页面与 MCP 工具层均不可见，此处为查询层防御）
        return []

    group_ids = list(
        (await db.execute(
            select(PmcpGroupUser.group_id)
            .join(PmcpGroup, PmcpGroup.id == PmcpGroupUser.group_id)
            .where(PmcpGroupUser.user_id == user_id, PmcpGroup.status == 1)
        )).scalars().all()
    )
    if not group_ids:
        return []

    if resource == "datasource":
        ids = list(
            (await db.execute(
                select(PmcpGroupDatasource.datasource_id).where(PmcpGroupDatasource.group_id.in_(group_ids))
            )).scalars().all()
        )
    else:
        ids = list(
            (await db.execute(
                select(PmcpGroupServer.server_id).where(PmcpGroupServer.group_id.in_(group_ids))
            )).scalars().all()
        )
    return sorted(set(ids))
