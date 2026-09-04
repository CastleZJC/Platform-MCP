"""Skill 广场 MCP 工具（V3.0 M3.5，架构 §19.5.3 / §19.5.7，计划 F-33/F-34 / 需求 1.1.4）

CC 经 MCP 双通道浏览、检索、复制与屏蔽广场 Skill，与 Web 广场页共用同一领域服务
（:mod:`platform_mcp.skills.plaza` 读侧 + :mod:`platform_mcp.skills.plaza_service` 写侧），
避免装饰性直改：

- ``search_skills``：广场语义搜索（query → embedding → topK，按角色可见性 + 黑名单过滤，F-33）；
- ``suggest_similar_skills``：创建前相似推荐（merge 合并 / new 新增结论素材，F-29）；
- ``get_skill_readme``：README 内容（按 locale，广场副本或个人 Skill）；
- ``add_skill_to_my`` / ``remove_my_skill``：广场复制到个人库 / 移除（F-34）；
- ``block_skill`` / ``unblock_skill`` / ``list_blocked_skills``：黑名单屏蔽 / 撤销 / 清单（F-34）；
- ``list_my_skills``：个人库 Skill 清单 + 状态（黑名单过滤）。

全部工具三角色（admin/developer/一般用户）可见；一般用户对涉库/涉服务器广场副本的不可见由
:func:`platform_mcp.skills.plaza.plaza_visible_to_role` 在读侧统一裁决（双端同口径）。

传输适配复用 :mod:`platform_mcp.skills.ecosystem` 的会话编排（``_session_scope``：mutate+flush →
统一 commit）、身份贯通（``_build_actor`` → :class:`ReviewActor`）与 locale 消息（``_localized``）。
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from platform_mcp.common.exceptions import SkillError
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.decorator import register_skill
from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
    SkillReviewError,
)
from platform_mcp.skills.ecosystem import _build_actor, _localized, _session_scope
from platform_mcp.skills.models import PmcpSkillPlaza, PmcpSkillVersion
from platform_mcp.skills.plaza import (
    load_blocked_plaza_ids,
    load_blocked_skill_ids,
    plaza_visible_to_role,
    scan_plaza_similar,
    search_visible_plazas,
)
from platform_mcp.skills.plaza_service import (
    block_skill,
    copy_plaza_to_personal,
    list_blocked_skills,
    remove_my_skill,
    unblock_skill,
)
from platform_mcp.skills.versioning import generate_bilingual_readme

_TOOL_NAMES = {
    "search_skills",
    "suggest_similar_skills",
    "get_skill_readme",
    "add_skill_to_my",
    "remove_my_skill",
    "block_skill",
    "unblock_skill",
    "list_blocked_skills",
    "list_my_skills",
}


def _locale_pick(locale: str | None, zh: str, en: str) -> str:
    """按 locale 选取 README 文本（en-* → 英文，其余 → 中文，§19.5.2）。"""
    return en if (locale or "zh-CN").lower().startswith("en") else zh


def _build_tool_meta() -> list[ToolMeta]:
    return [
        ToolMeta(
            tool_name="search_skills",
            display_name="广场语义搜索",
            description=(
                "在 Skill 广场做语义搜索：传入自然语言 query，按 BGE-M3 / 降级哈希向量相似度（无向量时关键词"
                "兜底）降序返回 topK 已发布广场 Skill（含 similarity 分值 + 涉库/涉服务器标记）。结果按认证"
                "身份角色可见性过滤（一般用户不见涉库/涉服务器项）并排除本人黑名单屏蔽项（F-33）/ Semantic "
                "search over the Skill plaza: pass a natural-language query, returns topK published plaza skills "
                "ranked by vector similarity (keyword fallback), each with a similarity score and involve-flags. "
                "Results are filtered by your role visibility and exclude your blocked (blacklist) items (F-33)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            risk_level="LOW",
            timeout_seconds=60,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="suggest_similar_skills",
            display_name="相似Skill推荐",
            description=(
                "创建 Skill 前的广场相似推荐：传入待创建的 skill_name / description，扫描广场已发布 Skill 返回"
                "按相似度降序的推荐素材，每条含 recommendation=merge（建议合并到现有）/ new（建议新增）结论，"
                "供你判断是重复造轮子还是新建（F-29）/ Pre-creation similarity suggestion: pass the intended "
                "skill_name / description, scans the published plaza and returns similar skills ranked by "
                "similarity, each with recommendation=merge (fold into an existing skill) or new (create fresh) "
                "so you can decide whether to reuse or build new (F-29)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "description": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["skill_name"],
            },
            risk_level="LOW",
            timeout_seconds=60,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="get_skill_readme",
            display_name="获取Skill README",
            description=(
                "获取 Skill 的 README 内容（按 locale 返回中文或英文）：传 plaza_id 读广场副本（先做角色可见性"
                "校验，一般用户不可读涉库/涉服务器项），或传 skill_id 读自己个人库 Skill 的版本存档 README"
                "（无存档时按元数据重生成）/ Get a Skill's README (Chinese or English by locale): pass plaza_id "
                "for a plaza copy (role visibility checked; regular users cannot read database/server-involved "
                "items), or skill_id for your own personal skill's archived version README (regenerated from "
                "metadata when no archive exists)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plaza_id": {"type": "integer"},
                    "skill_id": {"type": "integer"},
                    "locale": {"type": "string"},
                },
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="add_skill_to_my",
            display_name="添加到我的",
            description=(
                "把广场 Skill 复制到个人库（“添加至我的”）：广场副本复制为个人 pmcp_skill（origin=PLAZA + "
                "plaza_id 链接 + status=ENABLED，已过审可直接经 MCP 使用），skill_code 冲突时派生 "
                "{code}-{username}。一般用户不可复制涉库/涉服务器项（返回 10004）/ Copy a plaza skill into your "
                "personal library (“add to mine”): becomes a personal skill (origin=PLAZA, plaza_id linked, "
                "status=ENABLED, already reviewed so immediately MCP-usable); a conflicting skill_code is derived "
                "as {code}-{username}. Regular users cannot copy database/server-involved items (returns 10004)"
            ),
            input_schema={
                "type": "object",
                "properties": {"plaza_id": {"type": "integer"}},
                "required": ["plaza_id"],
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="remove_my_skill",
            display_name="移除我的Skill",
            description=(
                "移除个人库中自己的 Skill（仅本人；内置装饰器 Skill database/server 不可移除，返回 10003）；"
                "广场副本独立于个人库，移除个人复制体不影响广场已发布版本（F-29）/ Remove a skill from your own "
                "personal library (yours only; built-in decorator skills database/server cannot be removed, "
                "returns 10003). The plaza copy is independent, so removing your personal copy never affects the "
                "published plaza version (F-29)"
            ),
            input_schema={
                "type": "object",
                "properties": {"skill_id": {"type": "integer"}},
                "required": ["skill_id"],
            },
            risk_level="MEDIUM",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="block_skill",
            display_name="屏蔽Skill",
            description=(
                "屏蔽广场或个人 Skill（黑名单，F-34）：屏蔽后 Web + MCP 双端不再出现（仅黑名单页可见），可经 "
                "unblock_skill 撤销。plaza_id / skill_id 二选一（同时给出或同时为空返回 10003）；重复屏蔽幂等 "
                "/ Block a plaza or personal skill (blacklist, F-34): it disappears from both Web and MCP (visible "
                "only on the blacklist page) until unblocked. Pass exactly one of plaza_id / skill_id (both or "
                "neither returns 10003); repeat blocks are idempotent"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plaza_id": {"type": "integer"},
                    "skill_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="unblock_skill",
            display_name="撤销屏蔽",
            description=(
                "撤销屏蔽（F-34）：撤销后恢复 Web + MCP 双端可见。plaza_id / skill_id 二选一；目标不存在视为"
                "幂等成功 / Unblock a skill (F-34): restores visibility on both Web and MCP. Pass exactly one of "
                "plaza_id / skill_id; a missing target is treated as idempotent success"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plaza_id": {"type": "integer"},
                    "skill_id": {"type": "integer"},
                },
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="list_blocked_skills",
            display_name="黑名单清单",
            description=(
                "列出本人黑名单清单（仅黑名单页可见的已屏蔽广场/个人 Skill，F-34），每条附 target_type"
                "（plaza/skill）+ 展示信息（skill_code/skill_name）+ 屏蔽原因 / List your blacklist (blocked "
                "plaza/personal skills visible only on the blacklist page, F-34), each with target_type "
                "(plaza/skill), display info (skill_code/skill_name) and the block reason"
            ),
            input_schema={"type": "object", "properties": {}},
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="list_my_skills",
            display_name="我的Skill清单",
            description=(
                "列出本人个人库 Skill 清单 + 状态（DRAFT/PENDING_REVIEW/ENABLED/... 8 状态机）、分享状态、来源"
                "（ORIGINAL/PLAZA）与 plaza_id 链接；已屏蔽（黑名单 target_skill_id）项不出现（仅黑名单页可见）"
                "/ List your personal skills with status (the 8-state lifecycle), share status, origin "
                "(ORIGINAL/PLAZA) and plaza_id link; blocked items (blacklist target_skill_id) are excluded "
                "(visible only on the blacklist page)"
            ),
            input_schema={"type": "object", "properties": {}},
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=False,
        ),
    ]


@register_skill("skill_plaza")
class SkillPlazaToolsSkill:
    """Skill 广场双通道工具集（MCP 传输适配层，业务委托 plaza / plaza_service）。"""

    def skill_name(self) -> str:
        return "skill_plaza"

    def list_tools(self) -> list[ToolMeta]:
        return _build_tool_meta()

    async def validate(self, tool_name: str, params: dict) -> dict:
        if tool_name == "search_skills":
            if not str(params.get("query") or "").strip():
                raise SkillError("query 参数必填")
        elif tool_name == "suggest_similar_skills":
            if not str(params.get("skill_name") or "").strip():
                raise SkillError("skill_name 参数必填")
        elif tool_name == "get_skill_readme":
            if params.get("plaza_id") is None and params.get("skill_id") is None:
                raise SkillError("须传 plaza_id 或 skill_id 之一")
        elif tool_name == "add_skill_to_my":
            if params.get("plaza_id") is None:
                raise SkillError("plaza_id 参数必填")
        elif tool_name == "remove_my_skill":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
        elif tool_name in ("block_skill", "unblock_skill"):
            if params.get("plaza_id") is None and params.get("skill_id") is None:
                raise SkillError("须传 plaza_id 或 skill_id 之一")
        return params

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any:
        if tool_name == "search_skills":
            return await self._search_skills(params, context)
        if tool_name == "suggest_similar_skills":
            return await self._suggest_similar_skills(params, context)
        if tool_name == "get_skill_readme":
            return await self._get_skill_readme(params, context)
        if tool_name == "add_skill_to_my":
            return await self._add_skill_to_my(params, context)
        if tool_name == "remove_my_skill":
            return await self._remove_my_skill(params, context)
        if tool_name == "block_skill":
            return await self._block_skill(params, context)
        if tool_name == "unblock_skill":
            return await self._unblock_skill(params, context)
        if tool_name == "list_blocked_skills":
            return await self._list_blocked_skills(context)
        if tool_name == "list_my_skills":
            return await self._list_my_skills(context)
        raise NotImplementedError(f"Tool {tool_name} 未实现")

    def support(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # --- Tool 实现 ---

    async def _search_skills(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        query = str(params["query"]).strip()
        top_k = int(params.get("top_k") or 10)
        async with _session_scope() as session:
            blocked = await load_blocked_plaza_ids(session, actor.user_id)
            items = await search_visible_plazas(
                session, actor.role_code, query, blocked_plaza_ids=blocked, top_k=top_k
            )
            logger.info("MCP search_skills: query={!r} role={} hits={}", query, actor.role_code, len(items))
            return {
                "success": True,
                "query": query,
                "total": len(items),
                "items": items,
                "message": _localized(
                    actor,
                    f"广场语义搜索命中 {len(items)} 条（已按角色可见性与黑名单过滤）",
                    f"Plaza semantic search returned {len(items)} result(s), filtered by role visibility and blacklist",
                ),
            }

    async def _suggest_similar_skills(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_name = str(params["skill_name"]).strip()
        description = params.get("description")
        limit = int(params.get("limit") or 5)
        async with _session_scope() as session:
            similar = await scan_plaza_similar(session, skill_name, description, limit=limit)
            recommendation = similar[0]["recommendation"] if similar else "new"
            return {
                "success": True,
                "skill_name": skill_name,
                "recommendation": recommendation,
                "similar_skills": similar,
                "message": _localized(
                    actor,
                    f"相似推荐 {len(similar)} 条，综合结论：{'建议合并到现有' if recommendation == 'merge' else '建议新增'}",
                    f"{len(similar)} similar skill(s); overall: {'merge into an existing skill' if recommendation == 'merge' else 'create a new skill'}",
                ),
            }

    async def _get_skill_readme(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        plaza_id = params.get("plaza_id")
        skill_id = params.get("skill_id")
        locale = params.get("locale") or actor.locale
        async with _session_scope() as session:
            if plaza_id is not None:
                plaza = await session.get(PmcpSkillPlaza, int(plaza_id))
                if plaza is None:
                    raise SkillReviewError("广场 Skill 不存在", code=CODE_NOT_FOUND)
                if not plaza_visible_to_role(plaza.status, plaza.involve_flags, actor.role_code):
                    raise SkillReviewError("无权查看该广场 Skill（涉库/涉服务器对一般用户不可见）", code=CODE_FORBIDDEN)
                code, name = plaza.skill_code, plaza.skill_name
                zh, en = generate_bilingual_readme(
                    plaza.skill_name, plaza.description, plaza.source_path or "", plaza.version or "0.1.0"
                )
            elif skill_id is not None:
                skill = await session.get(PmcpSkill, int(skill_id))
                if skill is None:
                    raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
                if skill.inserted_by != actor.username and not actor.is_admin:
                    raise SkillReviewError("无权查看他人 Skill README", code=CODE_FORBIDDEN)
                code, name = skill.skill_code, skill.skill_name
                version = (
                    await session.execute(
                        select(PmcpSkillVersion)
                        .where(PmcpSkillVersion.skill_id == skill.id)
                        .order_by(PmcpSkillVersion.id.desc())
                    )
                ).scalars().first()
                zh = (version.readme_zh if version else None) or ""
                en = (version.readme_en if version else None) or ""
                if not zh and not en:
                    zh, en = generate_bilingual_readme(
                        skill.skill_name, skill.description, skill.source_path or "", skill.version or "0.1.0"
                    )
            else:
                raise SkillReviewError("须传 plaza_id 或 skill_id 之一", code=CODE_INVALID_STATE)
            readme = _locale_pick(locale, zh, en)
            return {
                "success": True,
                "skill_code": code,
                "skill_name": name,
                "locale": locale or "zh-CN",
                "readme": readme,
                "message": _localized(actor, "已返回 README 内容", "README content returned"),
            }

    async def _add_skill_to_my(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        plaza_id = int(params["plaza_id"])
        async with _session_scope() as session:
            skill = await copy_plaza_to_personal(session, plaza_id, actor, channel="mcp")
            logger.info("MCP add_skill_to_my: plaza_id={} → code={} owner={}", plaza_id, skill.skill_code, actor.username)
            return {
                "success": True,
                "skill_id": skill.id,
                "skill_code": skill.skill_code,
                "skill_name": skill.skill_name,
                "origin": skill.origin,
                "plaza_id": skill.plaza_id,
                "status": skill.status,
                "message": _localized(
                    actor,
                    f"已复制到个人库（{skill.skill_code}），status=ENABLED 可直接使用",
                    f"Copied to your library ({skill.skill_code}); status=ENABLED, ready to use",
                ),
            }

    async def _remove_my_skill(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        async with _session_scope() as session:
            await remove_my_skill(session, skill_id, actor, channel="mcp")
            return {
                "success": True,
                "skill_id": skill_id,
                "message": _localized(actor, "已移除个人库 Skill", "Personal skill removed"),
            }

    async def _block_skill(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        plaza_id = params.get("plaza_id")
        skill_id = params.get("skill_id")
        reason = params.get("reason")
        async with _session_scope() as session:
            entry = await block_skill(
                session,
                actor,
                plaza_id=int(plaza_id) if plaza_id is not None else None,
                skill_id=int(skill_id) if skill_id is not None else None,
                reason=reason,
                channel="mcp",
            )
            return {
                "success": True,
                "id": entry.id,
                "plaza_id": entry.target_plaza_id,
                "skill_id": entry.target_skill_id,
                "message": _localized(
                    actor, "已屏蔽（双端不再出现，仅黑名单页可见，可撤销）",
                    "Blocked (hidden on both Web and MCP, visible only on the blacklist page, reversible)",
                ),
            }

    async def _unblock_skill(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        plaza_id = params.get("plaza_id")
        skill_id = params.get("skill_id")
        async with _session_scope() as session:
            await unblock_skill(
                session,
                actor,
                plaza_id=int(plaza_id) if plaza_id is not None else None,
                skill_id=int(skill_id) if skill_id is not None else None,
                channel="mcp",
            )
            return {
                "success": True,
                "message": _localized(actor, "已撤销屏蔽（恢复双端可见）", "Unblocked (visible again on both Web and MCP)"),
            }

    async def _list_blocked_skills(self, context: Any) -> dict:
        actor = _build_actor(context)
        async with _session_scope() as session:
            items = await list_blocked_skills(session, actor.user_id)
            return {
                "success": True,
                "total": len(items),
                "items": items,
                "message": _localized(actor, f"黑名单 {len(items)} 条", f"{len(items)} blacklisted item(s)"),
            }

    async def _list_my_skills(self, context: Any) -> dict:
        actor = _build_actor(context)
        async with _session_scope() as session:
            blocked = await load_blocked_skill_ids(session, actor.user_id)
            rows = (
                await session.execute(
                    select(PmcpSkill).where(PmcpSkill.inserted_by == actor.username).order_by(PmcpSkill.id.desc())
                )
            ).scalars().all()
            items = [
                {
                    "skill_id": s.id,
                    "skill_code": s.skill_code,
                    "skill_name": s.skill_name,
                    "description": s.description,
                    "status": s.status,
                    "version": s.version,
                    "share_status": s.share_status,
                    "origin": s.origin,
                    "plaza_id": s.plaza_id,
                }
                for s in rows
                if s.id not in blocked
            ]
            return {
                "success": True,
                "total": len(items),
                "items": items,
                "message": _localized(
                    actor, f"个人库 {len(items)} 个 Skill（已排除屏蔽项）",
                    f"{len(items)} personal skill(s), blocked items excluded",
                ),
            }
