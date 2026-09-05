"""通知分发与组管理支撑（V3.0 M5，架构 §19.5.5 / 计划 5.2-5.3）

核心 :func:`dispatch_notification` —— 捕捉点统一入口：

- 读提醒事项组（``pmcp_notify_group``）——不存在或 ``enabled=0`` 静默返回（F-37 停用组静默）；
- ``{{param}}`` 模板渲染（缺参渲染为空串，F-39）；
- 收件人 = 组成员邮箱（join ``pmcp_user`` 取当前值，无邮箱/停用账号跳过）
  **∪** 调用方 ``extra_recipients``（本人直发类：API Key 变更→本人、审核结果→提交人），
  按邮箱去重（∪ 语义，F-37）；
- 渲染结果按收件人逐条落 ``pmcp_notify_outbox``（outbox 模式，F-38）——**不在业务事务内
  发送**，Web 进程周期 flush 统一发送（部署原则 #5 无 fire-and-forget）；
- 独立 session + 异常全捕获：通知链路任何故障不阻断业务（log warning 留痕）。

调用方（捕捉点，§19.5.5）：

- ``audit/logger.py:write_audit_log`` 尾部路由（db_high_op / server_high_op）；
- ``review/service.py`` 审核流程点（skill_review：提审/重提/通过/合并/拒绝/撤回）；
- ``api/users.py`` / ``api/api_keys.py`` / ``auth/service.py``（user_mgmt 安全事件 + 登录锁定）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from platform_mcp.notify.models import PmcpNotifyGroup, PmcpNotifyGroupMember, PmcpNotifyOutbox

# 四提醒事项（架构 §19.5.5，2026-09-02 定稿）
NOTIFY_TYPES = ("db_high_op", "server_high_op", "skill_review", "user_mgmt")
NOTIFY_TYPE_SET = frozenset(NOTIFY_TYPES)

# 错误码（notify 域 13xxx）
CODE_GROUP_NOT_FOUND = 13001
CODE_MEMBER_NOT_ADMIN = 13002

# 模板参数占位：{{key}} / {{ key }}（字母数字下划线；未知键渲染为空串）
_PARAM_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def render_template(template: str, params: dict) -> str:
    """``{{key}}`` 参数替换（F-39）：缺参/未定义键渲染为空串，模板编辑容错。"""
    return _PARAM_PATTERN.sub(lambda m: str(params.get(m.group(1), "")), template)


def _now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z").strip()


async def dispatch_notification(
    notify_type: str,
    params: dict,
    *,
    source: str,
    extra_recipients: list[tuple[int | None, str]] | None = None,
    trace_id: str | None = None,
    operator: str | None = None,
) -> int:
    """按事项组分发通知 → 落 outbox（不发送）。返回写入条数（0=静默/无收件人/异常）。

    - ``source``：捕捉点标识（audit_route/review/user_mgmt/lockout/test），outbox 审计列；
    - ``extra_recipients``：``[(user_id, email)]`` 本人直发类收件人（与组成员按邮箱去重）；
    - ``params`` 缺 ``time`` 时自动补当前时间（各捕捉点免重复格式化）。
    """
    if notify_type not in NOTIFY_TYPE_SET:
        logger.warning("notify dispatch: unknown notify_type {}", notify_type)
        return 0
    try:
        from platform_mcp.common.database import get_session_factory
        from platform_mcp.auth.models import PmcpUser

        if "time" not in params:
            params = {**params, "time": _now_str()}

        async with get_session_factory()() as session:
            group = (
                await session.execute(
                    select(PmcpNotifyGroup).where(PmcpNotifyGroup.notify_type == notify_type)
                )
            ).scalar_one_or_none()
            if group is None or group.enabled != 1:
                return 0  # 未 seed / 停用组静默（F-37）

            # 收件人：组成员（启用账号 + 有邮箱）∪ extra（按邮箱去重，extra 覆盖保留 user_id）
            member_rows = (
                await session.execute(
                    select(PmcpUser.id, PmcpUser.email)
                    .join(PmcpNotifyGroupMember, PmcpNotifyGroupMember.user_id == PmcpUser.id)
                    .where(PmcpNotifyGroupMember.group_id == group.id, PmcpUser.status == 1)
                )
            ).all()
            recipients: dict[str, int | None] = {}
            for user_id, email in member_rows:
                if email:
                    recipients.setdefault(email.strip(), user_id)
            for user_id, email in extra_recipients or []:
                text = str(email or "").strip()
                if text:
                    recipients[text] = user_id
            if not recipients:
                return 0  # 无收件人：无成员且无直发目标，静默

            subject = render_template(group.subject_template, params)
            body = render_template(group.body_template, params)
            for email, user_id in recipients.items():
                session.add(
                    PmcpNotifyOutbox(
                        notify_type=notify_type,
                        source=source,
                        recipient=email,
                        recipient_user_id=user_id,
                        subject=subject,
                        body=body,
                        trace_id=trace_id,
                        inserted_by=operator,
                    )
                )
            await session.commit()
            return len(recipients)
    except Exception as e:  # noqa: BLE001 - 通知链路故障不阻断业务（F-38 outbox 先落库语义）
        logger.warning("notify dispatch failed (non-fatal, type={} source={}): {}", notify_type, source, e)
        return 0
