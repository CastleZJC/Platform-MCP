"""Skill 广场动作服务（V3.0 M3.4，架构 §19.5.3 / §19.5.7，计划 F-34 / 需求 1.1.4）

承接广场的写侧动作，Web API（:mod:`platform_mcp.api.plaza`）与 MCP 生态工具
（:mod:`platform_mcp.skills.ecosystem`）双端共用同一编排，避免装饰性直改：

- :func:`copy_plaza_to_personal` —— "添加至我的 / 复制到个人库"（``add_skill_to_my``）：广场副本复制为
  个人库 ``pmcp_skill``（``origin=PLAZA`` + ``plaza_id`` 链接 + ``status=ENABLED``，已过审可直接 MCP 使用）；
- :func:`remove_my_skill` —— 移除个人库中自己的 Skill（``remove_my_skill``，内置装饰器 Skill 不可移除）；
- :func:`block_skill` / :func:`unblock_skill` / :func:`list_blocked_skills` —— 黑名单屏蔽/撤销/清单（F-34，
  屏蔽后 Web + MCP 双端不可见，仅黑名单页可见）；
- :func:`disable_plaza_skill` —— 停用广场 Skill（仅 admin，Web 端管理动作）：停用后对所有角色双端不可见，
  版本存档与审计保留，恢复路径为再次提交分享重新过审；
- :func:`rollback_plaza_version` —— 广场版本回退（仅 admin，设计定稿⑦）：归档快照复制回生效目录，
  不新建版本行（内容=归档版）；回滚即版本变更，持有者副本同走迭代标记（无邮件），README 迭代段落
  以「当前生效版本 ≠ 最新归档版」尾行呈现。

事务边界：服务层 ``mutate + flush``，**不 commit**（与 review.service / process_skill_upload 一致，
由 ``get_db`` 统一提交）；审计经 ``write_audit_log`` 独立 session 内部 commit。

skill_code 唯一性决策（批次 6.2 修订，2026-09-11）：``pmcp_skill.skill_code`` 全局唯一，广场副本可被多名
用户复制。复制冲突不再自动派生 ``{code}-{username}``（派生码退役），改为返回 **10006 + 结构化选项**
（``overwrite`` 覆盖本人旧副本 / ``retry``+``new_code`` 更名重试，双端一致）；与广场的关联以 ``plaza_id``
为准（review 合并流优先按 ``plaza_id`` 查广场副本，不依赖 skill_code），复制体的分享迭代/合并链路不受更名影响。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    CODE_SKILL_CODE_CONFLICT,
    ReviewActor,
    SkillReviewError,
    _plaza_snapshot_dir,
    mark_plaza_holders_for_iteration,
)
from platform_mcp.skills.iteration_readme import refresh_plaza_readme_iteration
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillBlacklist, PmcpSkillPlaza
from platform_mcp.skills.plaza import plaza_visible_to_role


async def copy_plaza_to_personal(
    db: AsyncSession,
    plaza_id: int,
    actor: ReviewActor,
    *,
    channel: str = "web",
    conflict_resolution: str | None = None,
    new_code: str | None = None,
) -> PmcpSkill:
    """复制广场副本到当前用户个人库（``add_skill_to_my``，架构 §19.5.7；批次 6.2 冲突二选一）。

    可见性校验统一委托 :func:`plaza_visible_to_role`（一般用户不可复制涉库/涉服务器项，需求 1.1.4）。
    复制体：``origin=PLAZA`` + ``plaza_id`` 链接 + ``status=ENABLED``（广场副本已过审，直接可 MCP 使用）+
    ``register_method="copy"``（非内置，可被本人更新/移除）；源码路径/校验和/版本引用广场副本。

    ``skill_code`` 冲突（批次 6.2，10006 二选一，派生码 ``{code}-{username}`` 退役）：

    - 基编码被占且未传 ``conflict_resolution`` → 抛 10006，``data`` 携 ``conflict_skill_id /
      conflict_code / overwrite_available``（占用行为本人同广场 origin=PLAZA 副本时 overwrite_available=True，
      否则仅可更名重试）；
    - ``conflict_resolution="overwrite"``：仅限占用行=本人 ``origin=PLAZA`` 且 ``plaza_id`` 同源的副本
      ——内容覆盖保留行（刷新元数据/源路径/校验和/copied_from_plaza_version，置回 ENABLED）；
      他人占用或其他来源一律 10003；
    - ``conflict_resolution="retry"``：以 ``new_code`` 为新编码重试，新编码仍被占再抛 10006。
    """
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None or plaza.status != "PUBLISHED":
        raise SkillReviewError("广场 Skill 不存在或未发布", code=CODE_NOT_FOUND)
    if not plaza_visible_to_role(plaza.status, plaza.involve_flags, actor.role_code):
        raise SkillReviewError("无权复制该广场 Skill（涉库/涉服务器对一般用户不可见）", code=CODE_FORBIDDEN)

    skill_code = plaza.skill_code
    existing = (
        await db.execute(select(PmcpSkill).where(PmcpSkill.skill_code == skill_code))
    ).scalar_one_or_none()
    if existing is not None:
        overwrite_available = (
            existing.inserted_by == actor.username
            and existing.origin == "PLAZA"
            and existing.plaza_id == plaza.id
        )
        if conflict_resolution is None:
            raise SkillReviewError(
                f"skill_code 冲突：{skill_code} 已被占用，请选择覆盖本地副本或更名后重试",
                code=CODE_SKILL_CODE_CONFLICT,
                data={
                    "conflict_skill_id": existing.id,
                    "conflict_code": existing.skill_code,
                    "overwrite_available": overwrite_available,
                },
            )
        if conflict_resolution == "overwrite":
            if not overwrite_available:
                raise SkillReviewError(
                    "该 skill_code 被他人 Skill 或其他来源占用，不可覆盖，请更名后重试",
                    code=CODE_INVALID_STATE,
                )
            existing.skill_name = plaza.skill_name
            existing.description = plaza.description
            existing.version = plaza.version
            existing.source_path = plaza.source_path
            existing.source_checksum = plaza.source_checksum
            existing.copied_from_plaza_version = plaza.version
            existing.status = "ENABLED"
            existing.share_status = "shared"
            existing.updated_by = actor.username
            await db.flush()
            await _audit(
                actor,
                "copy_from_plaza_overwrite",
                resource_id=skill_code,
                summary=f"覆盖本地副本（广场复制）：{plaza.skill_code} → {skill_code}",
                extra={"plaza_id": plaza.id, "plaza_skill_code": plaza.skill_code, "channel": channel},
            )
            return existing
        if conflict_resolution == "retry":
            candidate = str(new_code or "").strip()
            if not candidate:
                raise SkillReviewError("更名重试须传 new_code", code=CODE_INVALID_STATE)
            conflict_row = (
                await db.execute(select(PmcpSkill).where(PmcpSkill.skill_code == candidate))
            ).scalar_one_or_none()
            if conflict_row is not None:
                raise SkillReviewError(
                    f"skill_code 冲突：{candidate} 已被占用，请换一个编码重试",
                    code=CODE_SKILL_CODE_CONFLICT,
                    data={
                        "conflict_skill_id": conflict_row.id,
                        "conflict_code": conflict_row.skill_code,
                        "overwrite_available": (
                            conflict_row.inserted_by == actor.username
                            and conflict_row.origin == "PLAZA"
                            and conflict_row.plaza_id == plaza.id
                        ),
                    },
                )
            skill_code = candidate
        else:
            raise SkillReviewError(
                f"非法 conflict_resolution：{conflict_resolution}（overwrite | retry）",
                code=CODE_INVALID_STATE,
            )

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
        copied_from_plaza_version=plaza.version,
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


async def rollback_plaza_version(
    db: AsyncSession,
    plaza_id: int,
    version: str,
    actor: ReviewActor,
    *,
    note: str | None = None,
    channel: str = "web",
) -> dict:
    """广场版本回退（仅 admin，设计定稿⑦，2026-09-11）。

    归档快照（``pmcp_plaza_version.snapshot_path`` → ``_plaza_versions/{pid}/{version}/``）整目录
    复制回生效目录 ``_plaza/{pid}/``，广场行 ``version/source_path/source_checksum/updated_by``
    切到归档版；**不新建版本行**（回滚内容=归档版，版本史保持连续）。回滚即版本变更：
    持有者副本经 :func:`mark_plaza_holders_for_iteration` 批量置迭代态（无邮件，非阻断），
    README 迭代段落经 ``refresh_plaza_readme_iteration`` 以「当前生效版本 ≠ 最新归档版」
    尾行呈现（写盘失败不阻断）。``scripts/_rollback_plaza_version.py`` 保留脚本壳委托本函数。
    """
    if not actor.is_admin:
        raise SkillReviewError("仅 admin 可回退广场版本", code=CODE_FORBIDDEN)
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None:
        raise SkillReviewError("广场 Skill 不存在", code=CODE_NOT_FOUND)
    version_row = (
        await db.execute(
            select(PmcpPlazaVersion).where(
                PmcpPlazaVersion.plaza_id == plaza_id, PmcpPlazaVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if version_row is None:
        raise SkillReviewError(f"版本 {version} 的归档不存在", code=CODE_NOT_FOUND)
    snapshot_path = version_row.snapshot_path
    if not snapshot_path or not Path(snapshot_path).is_dir():
        raise SkillReviewError(
            f"版本 {version} 的快照目录缺失：{snapshot_path}", code=CODE_INVALID_STATE
        )
    snapshot = Path(snapshot_path)

    old_version = plaza.version
    live = _plaza_snapshot_dir(plaza_id)
    if live.exists():
        shutil.rmtree(live)
    shutil.copytree(snapshot, live)
    file_count = sum(1 for p in live.rglob("*") if p.is_file())

    plaza.version = version
    plaza.source_path = str(live)
    if version_row.checksum:
        plaza.source_checksum = version_row.checksum
    plaza.updated_by = actor.username
    await db.flush()

    await refresh_plaza_readme_iteration(db, plaza)
    holders_marked = await mark_plaza_holders_for_iteration(
        db, plaza_id=plaza.id, new_version=version, actor=actor, reason="rollback"
    )
    await _audit(
        actor,
        "rollback_plaza_version",
        resource_id=plaza.skill_code,
        summary=f"广场版本回退：{plaza.skill_code} v{old_version} -> v{version}",
        extra={
            "plaza_id": plaza.id,
            "from_version": old_version,
            "to_version": version,
            "note": note,
            "files": file_count,
            "holders_marked": holders_marked,
            "channel": channel,
        },
    )
    return {
        "plaza_id": plaza.id,
        "skill_code": plaza.skill_code,
        "from_version": old_version,
        "to_version": version,
        "file_count": file_count,
        "holders_marked": holders_marked,
    }


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
