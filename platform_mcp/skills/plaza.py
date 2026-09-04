"""Skill 广场相似度扫描 + 语义搜索 + 涉库标记派生（V3.0 M3，架构 §19.5.3 / §19.5.6）

为「创建前相似推荐」（F-29）、「版本化审核报告的广场比对结论」（F-28）、「广场语义搜索」
（F-33）与「涉库/涉服务器标记派生」（F-23/需求 1.1.4）提供广场已发布 Skill 的相似度打分与
``merge``（合并到现有）/ ``new``（新增）推荐素材。

中性领域模块：仅依赖 ORM 模型 :class:`platform_mcp.skills.models.PmcpSkillPlaza` 与向量栈
:mod:`platform_mcp.skills.embedding`，不依赖审核业务层（review）或 MCP 适配层（ecosystem），
故 Web 上传链路（:mod:`platform_mcp.skills.upload`）、MCP 草稿链路
（:mod:`platform_mcp.skills.ecosystem.draft`）与审核服务（:mod:`platform_mcp.review.service`）
可共享而无错误方向依赖。

打分（M3.2）：优先 BGE-M3 / 降级哈希向量余弦（:mod:`platform_mcp.skills.embedding`）；广场副本
尚未建向量时回退关键词重叠度粗排（名称权重高于描述）。返回契约
（plaza_id/skill_code/skill_name/description/version/similarity/recommendation）跨打分方式保持不变。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.skills.embedding import (
    cosine_similarity,
    create_embedding_store,
    embed_text,
    tokenize,
)
from platform_mcp.skills.models import PmcpSkillBlacklist, PmcpSkillPlaza

_SIMILAR_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "skill", "skills", "的", "了", "和", "与"}
)
_MERGE_THRESHOLD = 0.5

#: 涉库/涉服务器标记（audit R2-xx=数据库 / R3-xx=服务器，架构 §19.5.3）
INVOLVE_DATABASE = "database"
INVOLVE_SERVER = "server"

#: 一般用户角色（V3.0 第三角色，无 database/server 权限）；带涉库/涉服务器标记的广场 Skill 对其双端不可见
REGULAR_USER_ROLE = "user"
#: 受限标记集合（命中任一即对一般用户不可见，架构 §19.5.3 / 需求 1.1.4）
_RESTRICTED_FLAGS = frozenset({INVOLVE_DATABASE, INVOLVE_SERVER})


def derive_involve_flags(audit_result: dict | None) -> list[str]:
    """由 ``audit_result`` JSONB 的 R2-xx / R3-xx 规则命中派生涉库/涉服务器标记（架构 §19.5.3）。

    R2-xx（直连执行 DML/DDL、硬编码数据库连接）→ ``database``；R3-xx（外部 HTTP、网络监听）→ ``server``。
    带标记的广场 Skill 对一般用户（无 database/server 权限）在 Web 与 MCP 双端均不可见（需求 1.1.4）。
    返回排序去重列表（``[]`` = 无涉库/涉服务器）。
    """
    flags: set[str] = set()
    for failed in (audit_result or {}).get("failed_rules", []) or []:
        rule_id = str(failed.get("rule_id", ""))
        if rule_id.startswith("R2"):
            flags.add(INVOLVE_DATABASE)
        elif rule_id.startswith("R3"):
            flags.add(INVOLVE_SERVER)
    return sorted(flags)


def involves_restricted(involve_flags: list | None) -> bool:
    """广场副本是否带受限标记（涉库/涉服务器）——命中即对一般用户不可见。"""
    return bool(involve_flags) and any(f in _RESTRICTED_FLAGS for f in (involve_flags or []))


def plaza_visible_to_role(status: str | None, involve_flags: list | None, role_code: str | None) -> bool:
    """广场副本对某角色是否可见（架构 §19.5.3 / 需求 1.1.4，Web + MCP 双端共用同一判定）。

    仅 ``PUBLISHED`` 副本可见；一般用户（``role_code == "user"``，无 database/server 权限）额外
    排除带涉库/涉服务器标记的副本；admin / developer 可见全部已发布副本。
    """
    if status != "PUBLISHED":
        return False
    if role_code == REGULAR_USER_ROLE and involves_restricted(involve_flags):
        return False
    return True


def _overlap_score(name_tokens: set[str], desc_tokens: set[str], p_name: str | None, p_desc: str | None) -> float:
    """名称重叠（权重 0.6）+ 描述重叠（权重 0.4）的 Jaccard 相似度，返回 0~1（关键词兜底粗排）。"""
    p_name_tokens = set(tokenize(p_name))
    p_desc_tokens = set(tokenize(p_desc))
    name_jaccard = len(name_tokens & p_name_tokens) / (len(name_tokens | p_name_tokens) or 1)
    desc_jaccard = len(desc_tokens & p_desc_tokens) / (len(desc_tokens | p_desc_tokens) or 1)
    return 0.6 * name_jaccard + 0.4 * desc_jaccard


def _recommendation(similarity: float) -> str:
    return "merge" if similarity >= _MERGE_THRESHOLD else "new"


def _to_recommendation(plaza, similarity: float) -> dict:
    return {
        "plaza_id": plaza.id,
        "skill_code": plaza.skill_code,
        "skill_name": plaza.skill_name,
        "description": plaza.description,
        "version": plaza.version,
        "similarity": round(similarity, 3),
        "recommendation": _recommendation(similarity),
    }


async def index_plaza_embedding(db: AsyncSession, plaza_id: int, skill_name: str, description: str | None) -> None:
    """计算并写入广场副本的语义向量（发布/覆盖入广场时调用，架构 §19.5.6）。

    向量文本 = ``名称 + 描述``；provider 为 BGE-M3（权重就绪）或降级哈希。仅 ``flush`` 不 commit，
    事务由调用方（审核服务 ``_publish_to_plaza``）统一提交。
    """
    vector = await embed_text(f"{skill_name} {description or ''}".strip())
    store = await create_embedding_store(db)
    await store.upsert(plaza_id, vector)
    logger.debug("广场向量已建立：plaza_id={} backend={} dim={}", plaza_id, store.backend, len(vector))


async def search_plaza_semantic(
    db: AsyncSession, query: str, candidate_ids: list[int], *, top_k: int = 10
) -> list[tuple[int, float]]:
    """在 ``candidate_ids``（调用方按可见性/黑名单/涉库预筛）内语义搜索，返回 ``[(plaza_id, score)]`` 降序。

    可见性（状态/涉库/黑名单）由调用方先筛出候选，本函数只负责向量排序——业务与检索解耦（F-33）。
    """
    if not candidate_ids or not query.strip():
        return []
    vector = await embed_text(query)
    store = await create_embedding_store(db)
    return await store.search(vector, top_k, candidate_ids)


async def rank_plazas(
    db: AsyncSession, query: str, candidates: list[PmcpSkillPlaza]
) -> list[tuple[float, PmcpSkillPlaza]]:
    """对候选广场副本按与 ``query`` 的相似度降序打分，返回 ``[(score, plaza)]``。

    统一排序口径（相似推荐 / 广场语义搜索共用）：已建向量的副本用向量余弦（BGE-M3 / 降级哈希），
    尚未建向量的副本（历史/直接 seed）用关键词重叠度兜底；两者同为 0~1 相对分，可混合排序。
    """
    if not candidates or not query.strip():
        return []
    store = await create_embedding_store(db)
    query_vec = await embed_text(query)
    score_map = dict(await store.search(query_vec, len(candidates), [p.id for p in candidates]))
    q_tokens = set(tokenize(query))
    scored: list[tuple[float, PmcpSkillPlaza]] = []
    for plaza in candidates:
        if plaza.id in score_map:
            scored.append((float(score_map[plaza.id]), plaza))
        else:
            kw = _overlap_score(q_tokens, q_tokens, plaza.skill_name, plaza.description)
            if kw > 0:
                scored.append((kw, plaza))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


async def scan_plaza_similar(
    db: AsyncSession,
    skill_name: str,
    description: str | None,
    *,
    exclude_skill_code: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """扫描广场已发布 Skill，返回按相似度降序的推荐素材（含 merge/new 结论）。

    M3.2：优先向量余弦（BGE-M3 / 降级哈希）打分；广场副本尚未建向量时回退关键词重叠度粗排
    （统一委托 :func:`rank_plazas`）。返回契约（plaza_id/skill_code/skill_name/description/version/
    similarity/recommendation）跨打分方式保持不变。``exclude_skill_code`` 用于更新场景排除自身广场副本。
    """
    rows = (
        await db.execute(select(PmcpSkillPlaza).where(PmcpSkillPlaza.status == "PUBLISHED"))
    ).scalars().all()
    candidates = [
        p for p in rows if not (exclude_skill_code and p.skill_code == exclude_skill_code)
    ]
    if not candidates:
        return []
    scored = await rank_plazas(db, f"{skill_name} {description or ''}".strip(), candidates)
    recommendations = [_to_recommendation(plaza, score) for score, plaza in scored[:limit]]
    logger.debug("广场相似扫描：name={} 命中 {} 条", skill_name, len(recommendations))
    return recommendations


async def load_blocked_plaza_ids(db: AsyncSession, user_id: int | None) -> set[int]:
    """加载用户已屏蔽的广场副本 ID 集合（黑名单，F-34 / 架构 §19.5.3）。

    Web 广场列表/搜索与 MCP ``search_skills`` 双端均以此为 ``blocked_plaza_ids`` 过滤（屏蔽项仅黑名单页可见）。
    ``user_id`` 为空（未登录/无身份）时返回空集。
    """
    if not user_id:
        return set()
    rows = (
        await db.execute(
            select(PmcpSkillBlacklist.target_plaza_id).where(
                PmcpSkillBlacklist.user_id == user_id,
                PmcpSkillBlacklist.target_plaza_id.is_not(None),
            )
        )
    ).scalars().all()
    return {int(r) for r in rows if r is not None}


async def load_blocked_skill_ids(db: AsyncSession, user_id: int | None) -> set[int]:
    """加载用户已屏蔽的个人库 Skill ID 集合（黑名单 target_skill_id，F-34）。

    个人库列表（Web ``list_skills`` / MCP ``list_my_skills``）以此为过滤，屏蔽项仅黑名单页可见。
    """
    if not user_id:
        return set()
    rows = (
        await db.execute(
            select(PmcpSkillBlacklist.target_skill_id).where(
                PmcpSkillBlacklist.user_id == user_id,
                PmcpSkillBlacklist.target_skill_id.is_not(None),
            )
        )
    ).scalars().all()
    return {int(r) for r in rows if r is not None}


async def list_visible_plazas(
    db: AsyncSession,
    role_code: str | None,
    *,
    search: str | None = None,
    blocked_plaza_ids: set[int] | None = None,
) -> list[PmcpSkillPlaza]:
    """列出对 ``role_code`` 可见的已发布广场副本（架构 §19.5.3 / 需求 1.1.4）。

    可见性判定统一委托 :func:`plaza_visible_to_role`（PUBLISHED + 一般用户排除涉库/涉服务器），
    ``blocked_plaza_ids`` 为用户黑名单屏蔽集合（M3.4 传入，双端过滤）。Skill 量级 < 数千（VNF-02），
    Python 层过滤与可见性矩阵保持一致，不下推 SQL 以免涉库/黑名单逻辑双写。
    """
    rows = (
        await db.execute(select(PmcpSkillPlaza).where(PmcpSkillPlaza.status == "PUBLISHED").order_by(PmcpSkillPlaza.id))
    ).scalars().all()
    blocked = blocked_plaza_ids or set()
    visible = [
        p
        for p in rows
        if plaza_visible_to_role(p.status, p.involve_flags, role_code) and p.id not in blocked
    ]
    if search:
        kw = search.strip().lower()
        if kw:
            visible = [
                p
                for p in visible
                if kw in (p.skill_code or "").lower()
                or kw in (p.skill_name or "").lower()
                or kw in (p.description or "").lower()
            ]
    return visible


async def search_visible_plazas(
    db: AsyncSession,
    role_code: str | None,
    query: str,
    *,
    blocked_plaza_ids: set[int] | None = None,
    top_k: int = 10,
) -> list[dict]:
    """广场语义搜索（F-33）：在角色可见候选内按向量/关键词相似度降序返回，附涉库标记。

    可见性（状态/涉库/黑名单）由 :func:`list_visible_plazas` 预筛，排序委托 :func:`rank_plazas`——
    Web 广场页与 MCP ``search_skills`` 双端共用本函数，返回结构含 ``involve_flags`` 供前端标记展示。
    """
    candidates = await list_visible_plazas(db, role_code, blocked_plaza_ids=blocked_plaza_ids)
    scored = await rank_plazas(db, query, candidates)
    results: list[dict] = []
    for score, plaza in scored[:top_k]:
        results.append(
            {
                "plaza_id": plaza.id,
                "skill_code": plaza.skill_code,
                "skill_name": plaza.skill_name,
                "description": plaza.description,
                "version": plaza.version,
                "involve_flags": plaza.involve_flags or [],
                "iteration_note": plaza.iteration_note,
                "similarity": round(score, 3),
            }
        )
    logger.debug("广场语义搜索：query={!r} role={} 命中 {} 条", query, role_code, len(results))
    return results


__all__ = [
    "INVOLVE_DATABASE",
    "INVOLVE_SERVER",
    "REGULAR_USER_ROLE",
    "cosine_similarity",
    "derive_involve_flags",
    "index_plaza_embedding",
    "involves_restricted",
    "list_visible_plazas",
    "load_blocked_plaza_ids",
    "load_blocked_skill_ids",
    "plaza_visible_to_role",
    "rank_plazas",
    "scan_plaza_similar",
    "search_plaza_semantic",
    "search_visible_plazas",
]
