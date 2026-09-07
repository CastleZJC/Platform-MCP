"""内置 Skill 启动同步 — 装饰器注册的 Skill 自动落库 ``pmcp_skill``

MCP 接入指南 ``/guide/tools`` 与 Skill 管理按 ``pmcp_skill`` 展示；内置 Skill 此前
靠 ``scripts/_seed_skill.py`` 手工种子，生态 Skill 加入后页面展示不全（11/31 tools）。
本模块在 Web 进程启动时按 registry 内置清单（``BUILTIN_SKILL_CODES``）自动补齐：
插入行 status=ENABLED、register_method="decorator"、tool_count 实测；已有行仅刷新
tool_count，**不覆盖 admin 停用状态与用户编辑的名称/描述**。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.i18n import get_text
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.registry import BUILTIN_SKILL_CODES, get_skill_instance
from platform_mcp.review.state_machine import ReviewStatus

# 插入时的显示名（与既有种子行口径一致；更新路径不触碰已有行的名称）
_DISPLAY_NAMES: dict[str, str] = {
    "database": "Database Skill",
    "server": "Server Skill",
    "skill_ecosystem": "Skill Ecosystem",
    "skill_plaza": "Skill Plaza",
    "skill_account": "Skill Account",
}


async def sync_builtin_skills_to_db(db: AsyncSession) -> tuple[int, int]:
    """启动同步内置 Skill 到 ``pmcp_skill``，返回 ``(inserted, refreshed)``。"""
    inserted = refreshed = 0
    for code in BUILTIN_SKILL_CODES:
        instance = get_skill_instance(code)
        if instance is None:  # pragma: no cover - 清单与工厂同文件维护，不应失配
            continue
        tool_count = len(instance.list_tools())
        row = (await db.execute(
            select(PmcpSkill).where(PmcpSkill.skill_code == code)
        )).scalar_one_or_none()
        if row is None:
            db.add(PmcpSkill(
                skill_code=code,
                skill_name=_DISPLAY_NAMES.get(code, code),
                description=get_text(f"skill.desc.{code}", "zh-CN"),
                status=ReviewStatus.ENABLED,
                register_method="decorator",
                tool_count=tool_count,
                inserted_by="system",
                updated_by="system",
            ))
            inserted += 1
        elif row.tool_count != tool_count:
            row.tool_count = tool_count
            row.updated_by = "system"
            refreshed += 1
    if inserted or refreshed:
        await db.commit()
    logger.info("内置 Skill 启动同步: 新增 {} 刷新 {}", inserted, refreshed)
    return inserted, refreshed
