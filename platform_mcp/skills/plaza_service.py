"""Skill 广场动作服务（V3.0 M3.4，架构 §19.5.3 / §19.5.7，计划 F-34 / 需求 1.1.4）

承接广场的写侧动作，Web API（:mod:`platform_mcp.api.plaza`）与 MCP 生态工具
（:mod:`platform_mcp.skills.ecosystem`）双端共用同一编排，避免装饰性直改：

- :func:`copy_plaza_to_personal` —— "添加至我的 / 复制到个人库"（``add_skill_to_my``）：广场副本复制为
  个人库 ``pmcp_skill``（``origin=PLAZA`` + ``plaza_id`` 链接 + ``status=ENABLED``，已过审可直接 MCP 使用）；
- :func:`remove_my_skill` —— 移除个人库中自己的 Skill（``remove_my_skill``，内置装饰器 Skill 不可移除）；
- :func:`block_skill` / :func:`unblock_skill` / :func:`list_blocked_skills` —— 黑名单屏蔽/撤销/清单（F-34，
  屏蔽后 Web + MCP 双端不可见，仅黑名单页可见）；
- :func:`disable_plaza_skill` —— 停用广场 Skill（仅 admin，Web 端管理动作）：停用后对所有角色双端不可见，
  版本存档与审计保留，恢复路径为再次提交分享重新过审。

事务边界：服务层 ``mutate + flush``，**不 commit**（与 review.service / process_skill_upload 一致，
由 ``get_db`` 统一提交）；审计经 ``write_audit_log`` 独立 session 内部 commit。

skill_code 唯一性决策：``pmcp_skill.skill_code`` 全局唯一，而广场副本可被多名用户复制。复制时若基编码
已被占用，派生 ``{code}-{username}``（再冲突追加序号）；与广场的关联以 ``plaza_id`` 为准（review 合并流
优先按 ``plaza_id`` 查广场副本，不依赖 skill_code），保证复制体的分享迭代/合并链路正确。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
    SkillReviewError,
)
from platform_mcp.skills.models import PmcpSkillBlacklist, PmcpSkillPlaza
from platform_mcp.skills.plaza import plaza_visible_to_role


async def _skill_code_exists(db: AsyncSession, skill_code: str) -> bool:
    existing = (
        await db.execute(select(PmcpSkill.id).where(PmcpSkill.skill_code == skill_code))
    ).scalar_one_or_none()
    return existing is not None


async def _derive_unique_code(db: AsyncSession, base_code: str, username: str) -> str:
    """派生全局唯一 skill_code：基编码空闲则原样，否则 ``{base}-{username}[-n]``。"""
    if not await _skill_code_exists(db, base_code):
        return base_code
    candidate = f"{base_code}-{username}"
    seq = 2
    while await _skill_code_exists(db, candidate):
        candidate = f"{base_code}-{username}-{seq}"
        seq += 1
    return candidate


async def _audit(
    actor: ReviewActor,
    action: str,
    *,
    resource_id: str,
    summary: str,
    result_status: str = "success",
    error_message: str | None = None,
    extra: dict | None = None,
) -> None:
    detail: dict = {"action": action}
    if extra:
        detail.update(extra)
    await write_audit_log(
        trace_id=actor.trace_id,
        operator=actor.username,
        skill_name=resource_id,
        resource_type="skill",
        resource_id=resource_id,
        request_summary=summary,
        result_status=result_status,
        error_message=error_message,
        extra_data=detail,
    )


async def copy_plaza_to_personal(db: AsyncSession, plaza_id: int, actor: ReviewActor, *, channel: str = "web") -> PmcpSkill:
    """复制广场副本到当前用户个人库（``add_skill_to_my``，架构 §19.5.7）。

    可见性校验统一委托 :func:`plaza_visible_to_role`（一般用户不可复制涉库/涉服务器项，需求 1.1.4）。
    复制体：``origin=PLAZA`` + ``plaza_id`` 链接 + ``status=ENABLED``（广场副本已过审，直接可 MCP 使用）+
    ``register_method="copy"``（非内置，可被本人更新/移除）；源码路径/校验和/版本引用广场副本。
    """
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None or plaza.status != "PUBLISHED":
        raise SkillReviewError("广场 Skill 不存在或未发布", code=CODE_NOT_FOUND)
    if not plaza_visible_to_role(plaza.status, plaza.involve_flags, actor.role_code):
        raise SkillReviewError("无权复制该广场 Skill（涉库/涉服务器对一般用户不可见）", code=CODE_FORBIDDEN)

    skill_code = await _derive_unique_code(db, plaza.skill_code, actor.username)
    skill = PmcpSkill(
        skill_code=skill_code,
        skill_name=plaza.skill_name,
        description=plaza.description,
        status="ENABLED",
        register_method="copy",
        tool_count=0,
        source_path=plaza.source_path,
        source_checksum=plaza.source_checksum,
        version=plaza.version,
        audit_status="passed",
        audit_result=None,
        readme_generated=True,
        plaza_id=plaza.id,
        origin="PLAZA",
        share_status="shared",
        inserted_by=actor.username,
    )
    db.add(skill)
    await db.flush()
    await _audit(
        actor,
        "copy_from_plaza",
        resource_id=skill_code,
        summary=f"复制广场 Skill 到个人库：{plaza.skill_code} → {skill_code}",
        extra={"plaza_id": plaza.id, "plaza_skill_code": plaza.skill_code, "channel": channel},
    )
    return skill


async def remove_my_skill(db: AsyncSession, skill_id: int, actor: ReviewActor, *, channel: str = "web") -> None:
    """移除个人库中自己的 Skill（``remove_my_skill``）。

    仅本人可移除（F-29）；内置装饰器 Skill（database/server）不可移除（§19.5.7 仅 Web 管理，且不可移除）；
    广场副本独立于个人库（``pmcp_skill_plaza``），移除个人复制体不影响广场。
    """
    skill = await db.get(PmcpSkill, skill_id)
    if skill is None:
        raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
    if skill.inserted_by != actor.username and not actor.is_admin:
        raise SkillReviewError("无权移除他人 Skill", code=CODE_FORBIDDEN)
    if skill.register_method == "decorator":
        raise SkillReviewError("内置 Skill 不可移除", code=CODE_INVALID_STATE)
    code = skill.skill_code
    await db.delete(skill)
    await db.flush()
    await _audit(
        actor,
        "remove_my_skill",
        resource_id=code,
        summary=f"移除个人库 Skill：{code}",
        extra={"skill_id": skill_id, "origin": skill.origin, "channel": channel},
    )


async def block_skill(
    db: AsyncSession,
    actor: ReviewActor,
    *,
    plaza_id: int | None = None,
    skill_id: int | None = None,
    reason: str | None = None,
    channel: str = "web",
) -> PmcpSkillBlacklist:
    """屏蔽广场/个人 Skill（``block_skill``，F-34）：屏蔽后 Web + MCP 双端不可见，仅黑名单页可见。

    ``plaza_id`` / ``skill_id`` 二选一（同时给出或同时为空均拒绝）；重复屏蔽幂等返回既有记录。
    """
    if (plaza_id is None) == (skill_id is None):
        raise SkillReviewError("屏蔽目标须为 plaza_id / skill_id 二选一", code=CODE_INVALID_STATE)
    if not actor.user_id:
        raise SkillReviewError("无法确定屏蔽发起用户", code=CODE_FORBIDDEN)

    existing = (
        await db.execute(
            select(PmcpSkillBlacklist).where(
                PmcpSkillBlacklist.user_id == actor.user_id,
                PmcpSkillBlacklist.target_plaza_id == plaza_id if plaza_id is not None
                else PmcpSkillBlacklist.target_skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    entry = PmcpSkillBlacklist(
        user_id=actor.user_id,
        target_plaza_id=plaza_id,
        target_skill_id=skill_id,
        reason=reason,
        inserted_by=actor.username,
    )
    db.add(entry)
    await db.flush()
    await _audit(
        actor,
        "block_skill",
        resource_id=str(plaza_id if plaza_id is not None else skill_id),
        summary=f"屏蔽 Skill：{'广场' if plaza_id is not None else '个人'} #{plaza_id or skill_id}",
        extra={"plaza_id": plaza_id, "skill_id": skill_id, "reason": reason, "channel": channel},
    )
    return entry


async def unblock_skill(
    db: AsyncSession,
    actor: ReviewActor,
    *,
    plaza_id: int | None = None,
    skill_id: int | None = None,
    channel: str = "web",
) -> None:
    """撤销屏蔽（``unblock_skill``，F-34）：撤销后恢复双端可见。目标不存在视为幂等成功。"""
    if (plaza_id is None) == (skill_id is None):
        raise SkillReviewError("撤销目标须为 plaza_id / skill_id 二选一", code=CODE_INVALID_STATE)
    if not actor.user_id:
        raise SkillReviewError("无法确定撤销发起用户", code=CODE_FORBIDDEN)
    entry = (
        await db.execute(
            select(PmcpSkillBlacklist).where(
                PmcpSkillBlacklist.user_id == actor.user_id,
                PmcpSkillBlacklist.target_plaza_id == plaza_id if plaza_id is not None
                else PmcpSkillBlacklist.target_skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        return
    await db.delete(entry)
    await db.flush()
    await _audit(
        actor,
        "unblock_skill",
        resource_id=str(plaza_id if plaza_id is not None else skill_id),
        summary=f"撤销屏蔽 Skill：{'广场' if plaza_id is not None else '个人'} #{plaza_id or skill_id}",
        extra={"plaza_id": plaza_id, "skill_id": skill_id, "channel": channel},
    )


async def disable_plaza_skill(
    db: AsyncSession,
    plaza_id: int,
    actor: ReviewActor,
    *,
    channel: str = "web",
) -> PmcpSkillPlaza:
    """停用广场 Skill（仅 admin，Web 端管理动作，架构 §19.5.3）。

    停用后 ``plaza_visible_to_role`` 对所有角色返回不可见（Web 列表/搜索 + MCP 双端），个人库既有
    复制体不受影响；版本存档（``pmcp_skill_version``）与审计保留。幂等：已停用直接返回。
    恢复路径为再次提交分享重新过审（不提供独立启用动作）。
    """
    if not actor.is_admin:
        raise SkillReviewError("仅 admin 可停用广场 Skill", code=CODE_FORBIDDEN)
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None:
        raise SkillReviewError("广场 Skill 不存在", code=CODE_NOT_FOUND)
    if plaza.status == "DISABLED":
        return plaza
    plaza.status = "DISABLED"
    await db.flush()
    await _audit(
        actor,
        "disable_plaza_skill",
        resource_id=plaza.skill_code,
        summary=f"停用广场 Skill：{plaza.skill_code}",
        extra={"plaza_id": plaza.id, "channel": channel},
    )
    return plaza


async def list_blocked_skills(db: AsyncSession, user_id: int | None) -> list[dict]:
    """列出用户黑名单清单（仅黑名单页可见，F-34），附目标展示信息。"""
    if not user_id:
        return []
    entries = (
        await db.execute(
            select(PmcpSkillBlacklist)
            .where(PmcpSkillBlacklist.user_id == user_id)
            .order_by(PmcpSkillBlacklist.id.desc())
        )
    ).scalars().all()
    if not entries:
        return []

    plaza_ids = [e.target_plaza_id for e in entries if e.target_plaza_id is not None]
    skill_ids = [e.target_skill_id for e in entries if e.target_skill_id is not None]
    plaza_map: dict[int, PmcpSkillPlaza] = {}
    skill_map: dict[int, PmcpSkill] = {}
    if plaza_ids:
        plaza_rows = (
            await db.execute(select(PmcpSkillPlaza).where(PmcpSkillPlaza.id.in_(plaza_ids)))
        ).scalars().all()
        plaza_map = {p.id: p for p in plaza_rows}
    if skill_ids:
        skill_rows = (
            await db.execute(select(PmcpSkill).where(PmcpSkill.id.in_(skill_ids)))
        ).scalars().all()
        skill_map = {s.id: s for s in skill_rows}

    items: list[dict] = []
    for e in entries:
        if e.target_plaza_id is not None:
            target = plaza_map.get(e.target_plaza_id)
            items.append(
                {
                    "id": e.id,
                    "target_type": "plaza",
                    "target_id": e.target_plaza_id,
                    "skill_code": target.skill_code if target else None,
                    "skill_name": target.skill_name if target else None,
                    "reason": e.reason,
                    "created_at": e.inserted_at.isoformat() if e.inserted_at else None,
                }
            )
        elif e.target_skill_id is not None:
            target_s = skill_map.get(e.target_skill_id)
            items.append(
                {
                    "id": e.id,
                    "target_type": "skill",
                    "target_id": e.target_skill_id,
                    "skill_code": target_s.skill_code if target_s else None,
                    "skill_name": target_s.skill_name if target_s else None,
                    "reason": e.reason,
                    "created_at": e.inserted_at.isoformat() if e.inserted_at else None,
                }
            )
    return items
