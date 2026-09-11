"""个人库 Skill 自助动作服务（批次 6.1，设计定稿⑩，2026-09-11）

个人库补齐的写侧动作，Web API（:mod:`platform_mcp.api.skills`）与 MCP 生态工具
（:mod:`platform_mcp.skills.ecosystem`）双端共用：

- :func:`rename_my_skill` —— 重命名自己的 Skill（改 ``skill_code`` + 磁盘目录同步改名）。

事务边界：``mutate + flush`` 不 commit（与 plaza_service / review.service 一致，由调用方
``get_db`` / ``_session_scope`` 统一提交）；审计经 ``write_audit_log`` 独立 session 内部 commit。
"""

from __future__ import annotations

import re
from pathlib import Path

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

#: 可重命名的稳定态（过渡态 PENDING_REVIEW / SHARE_ITERATION / APPROVED 不可改码）
_RENAMABLE_STATES = frozenset({"DRAFT", "REJECTED", "WITHDRAWN", "ENABLED", "DISABLED"})

#: skill_code 形态（同时防目录穿越：仅字母数字开头 + 安全字符）
_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


async def rename_my_skill(
    db: AsyncSession,
    skill_id: int,
    new_code: str,
    actor: ReviewActor,
    *,
    channel: str = "web",
) -> PmcpSkill:
    """重命名自己的 Skill（批次 6.1：改 skill_code + 磁盘目录同步改名）。

    条件矩阵（全部满足才可改码，否则 10003）：

    - 仅本人（F-29 归属校验，admin 亦不代改——个人库编码是所有者的命名空间）；
    - 非内置装饰器（``register_method != "decorator"``）；
    - 非广场关联（``origin != "PLAZA"`` 且 ``plaza_id`` 为空——已分享 Skill 的编码锚定广场，
      仅可改显示名 skill_name，走 update 通道）；
    - 稳定态（DRAFT/REJECTED/WITHDRAWN/ENABLED/DISABLED；过渡态先撤回/解决迭代）。

    行为：同码幂等直接返回；新码被占 → 10003；磁盘目录 ``{upload_dir}/{old_code}`` 存在则改名
    （目标目录已存在 → 10003，旧目录缺失容忍为纯元数据改名）；``source_path`` 同步指向新目录。
    """
    skill = await db.get(PmcpSkill, skill_id)
    if skill is None:
        raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
    if skill.inserted_by != actor.username:
        raise SkillReviewError("仅本人可重命名自己的 Skill", code=CODE_FORBIDDEN)
    if skill.register_method == "decorator":
        raise SkillReviewError("内置装饰器 Skill 不可重命名", code=CODE_INVALID_STATE)
    if skill.origin == "PLAZA" or skill.plaza_id is not None:
        raise SkillReviewError(
            "已分享/广场关联的 Skill 不可改编码（仅可经更新通道改显示名）", code=CODE_INVALID_STATE
        )
    if skill.status not in _RENAMABLE_STATES:
        raise SkillReviewError(
            f"状态 {skill.status} 不可重命名（审核中请先撤回，分享迭代请先解决）", code=CODE_INVALID_STATE
        )

    new_code = str(new_code or "").strip()
    if not _CODE_PATTERN.fullmatch(new_code):
        raise SkillReviewError(
            f"skill_code 非法：{new_code!r}（仅字母数字开头，可含 . _ -）", code=CODE_INVALID_STATE
        )
    old_code = skill.skill_code
    if new_code == old_code:
        return skill

    existing = (
        await db.execute(select(PmcpSkill.id).where(PmcpSkill.skill_code == new_code))
    ).scalar_one_or_none()
    if existing is not None:
        raise SkillReviewError(f"skill_code 已被占用：{new_code}", code=CODE_INVALID_STATE)

    old_path = Path(skill.source_path) if skill.source_path else None
    if old_path is not None and old_path.is_dir():
        new_dir = old_path.parent / new_code
        if new_dir.exists():
            raise SkillReviewError(
                f"目标目录已存在：{new_dir}（请换一个编码或联系管理员清理）", code=CODE_INVALID_STATE
            )
        old_path.rename(new_dir)
        skill.source_path = str(new_dir)

    skill.skill_code = new_code
    skill.updated_by = actor.username
    await db.flush()
    await write_audit_log(
        trace_id=actor.trace_id,
        operator=actor.username,
        skill_name=new_code,
        resource_type="skill",
        resource_id=str(skill.id),
        request_summary=f"Skill 重命名：{old_code} → {new_code}",
        extra_data={"action": "rename", "old_code": old_code, "new_code": new_code, "channel": channel},
    )
    return skill
