"""009_notify_tables — 邮件组提醒（V3.0 M5，架构 §19.5.5 / 计划 5.1）

Revision ID: 009
Revises: 008
Create Date: 2026-09-05

变更内容：
1. pmcp_notify_group —— 四提醒事项组（notify_type 唯一：db_high_op / server_high_op /
   skill_review / user_mgmt）+ subject/body 参数化模板 + 参数描述（可改）+ enabled 独立启停；
   seed 四组默认中文模板（F-39）。
2. pmcp_notify_group_member —— 组成员（仅 admin 角色可入组，服务层录入校验 +
   无邮箱提示；UNIQUE(group_id, user_id)，发送时 join pmcp_user 取当前邮箱）。
3. pmcp_notify_outbox —— 发件箱（pending/sent/failed + retry_count + error_message +
   sent_at + trace_id；失败可重试、全程可审计，无 fire-and-forget，F-38）。
4. pmcp_user 加 failed_attempts / locked_until —— 连续登录失败锁定（F-37 user_mgmt
   捕捉点的功能前提：5 次失败锁 15 分钟，auth 服务层实现）。

迁移编号说明：架构 §19.5.8 原拆分口径为 008=notify / 009=KB，但 008 已被
「组去环境维度」（008_group_drop_env，M3R 后插入）占用 → notify 顺延 009、
三期 KB 顺延 010；编号一致性于 M6.3（F-42）终核同步文档。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 四提醒事项（架构 §19.5.5，2026-09-02 定稿）与默认模板（中文，管理员可编辑，F-39）
# 内置参数：{{user}}/{{resource}}/{{env}}/{{risk}}/{{time}}/{{reason}}/{{iteration_note}}/{{action}}
_NOTIFY_GROUPS: list[dict] = [
    {
        "notify_type": "db_high_op",
        "group_name": "生产高危数据库操作提醒组",
        "subject_template": "【Platform-MCP】生产高危数据库操作：{{resource}}（{{env}}）",
        "body_template": (
            "操作人：{{user}}\n"
            "目标资源：{{resource}}\n"
            "环境：{{env}}\n"
            "风险等级：{{risk}}\n"
            "时间：{{time}}\n"
            "概要：{{summary}}\n"
            "\n-- Platform-MCP 审计路由（PROD + HIGH/CRITICAL 自动触达）"
        ),
    },
    {
        "notify_type": "server_high_op",
        "group_name": "生产高危服务器操作提醒组",
        "subject_template": "【Platform-MCP】生产高危服务器操作：{{resource}}（{{env}}）",
        "body_template": (
            "操作人：{{user}}\n"
            "目标资源：{{resource}}\n"
            "环境：{{env}}\n"
            "风险等级：{{risk}}\n"
            "时间：{{time}}\n"
            "概要：{{summary}}\n"
            "\n-- Platform-MCP 审计路由（PROD + HIGH/CRITICAL 自动触达）"
        ),
    },
    {
        "notify_type": "skill_review",
        "group_name": "Skill 审核提醒组",
        "subject_template": "【Platform-MCP】Skill 审核事件：{{resource}}（{{action}}）",
        "body_template": (
            "操作人：{{user}}\n"
            "Skill：{{resource}}\n"
            "动作：{{action}}\n"
            "时间：{{time}}\n"
            "说明：{{reason}}{{iteration_note}}\n"
            "\n-- Platform-MCP Skill 审核流（提审/审核结果/撤回自动触达）"
        ),
    },
    {
        "notify_type": "user_mgmt",
        "group_name": "用户管理安全事件提醒组",
        "subject_template": "【Platform-MCP】用户管理安全事件：{{action}}",
        "body_template": (
            "操作人：{{user}}\n"
            "相关用户：{{resource}}\n"
            "动作：{{action}}\n"
            "时间：{{time}}\n"
            "说明：{{reason}}\n"
            "\n-- Platform-MCP 用户管理安全事件（创建/停用/角色变更/Key 重置/锁定自动触达）"
        ),
    },
]

# 参数描述（各组共用键域；param_descriptions 可改，架构 §19.5.5「参数描述可改」）
_PARAM_DESCRIPTIONS: dict[str, str] = {
    "user": "操作人用户名",
    "resource": "目标资源（数据源/服务器编码或 Skill 名/用户名）",
    "env": "环境编码（DEV/UAT/PROD）",
    "risk": "风险等级（LOW/MEDIUM/HIGH/CRITICAL）",
    "time": "事件时间",
    "summary": "请求概要",
    "reason": "说明 / 拒绝原因",
    "iteration_note": "迭代说明（merge）",
    "action": "动作（提交/通过/合并/拒绝/撤回/创建/停用/角色变更/Key 重置/锁定等）",
}


def upgrade() -> None:
    # 1. 提醒事项组
    op.create_table(
        "pmcp_notify_group",
        sa.Column("notify_type", sa.String(32), unique=True, nullable=False,
                  comment="提醒事项类型（db_high_op/server_high_op/skill_review/user_mgmt，架构 §19.5.5）"),
        sa.Column("group_name", sa.String(64), nullable=False, comment="组显示名"),
        sa.Column("subject_template", sa.Text(), nullable=False, comment="邮件主题模板（{{param}} 参数化）"),
        sa.Column("body_template", sa.Text(), nullable=False, comment="邮件正文模板（{{param}} 参数化）"),
        sa.Column("param_descriptions", postgresql.JSONB(), nullable=True,
                  comment="模板参数说明（key→描述，可改）"),
        sa.Column("enabled", sa.SmallInteger(), server_default="1", nullable=False,
                  comment="1-启用 0-停用（停用组静默，F-37）"),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        comment="邮件提醒事项组（V3.0 M5）",
    )

    # 2. 组成员（仅 admin 可入组——服务层录入校验；发送时 join 取当前邮箱）
    op.create_table(
        "pmcp_notify_group_member",
        sa.Column("group_id", sa.BigInteger(),
                  sa.ForeignKey("pmcp_notify_group.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("pmcp_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        sa.UniqueConstraint("group_id", "user_id", name="uq_notify_group_member"),
        comment="邮件提醒组成员（仅 admin 角色用户，架构 §19.5.5）",
    )

    # 3. 发件箱（outbox 模式：先落库后发送，失败可重试、全程可审计，F-38）
    op.create_table(
        "pmcp_notify_outbox",
        sa.Column("notify_type", sa.String(32), nullable=False, comment="提醒事项类型"),
        sa.Column("source", sa.String(32), nullable=False,
                  comment="捕捉点来源（audit_route/review/user_mgmt/lockout/test）"),
        sa.Column("recipient", sa.String(128), nullable=False, comment="收件人邮箱"),
        sa.Column("recipient_user_id", sa.BigInteger(), comment="收件人用户 id（本人直发类可追溯）"),
        sa.Column("subject", sa.Text(), nullable=False, comment="渲染后主题"),
        sa.Column("body", sa.Text(), nullable=False, comment="渲染后正文"),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False,
                  comment="pending-待发 sent-已发 failed-失败可重试"),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False, comment="已重试次数"),
        sa.Column("error_message", sa.Text(), comment="最近一次发送错误"),
        sa.Column("sent_at", sa.DateTime(timezone=True), comment="发送成功时间"),
        sa.Column("trace_id", sa.String(64), comment="审计链 trace_id"),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        comment="邮件发件箱（outbox 模式，V3.0 M5，F-38）",
    )
    op.create_index("ix_notify_outbox_status", "pmcp_notify_outbox", ["status"])

    # 4. 连续登录失败锁定字段（F-37 user_mgmt 捕捉点功能前提）
    op.add_column("pmcp_user", sa.Column("failed_attempts", sa.Integer(), server_default="0",
                                         nullable=False, comment="连续登录失败次数（成功登录清零）"))
    op.add_column("pmcp_user", sa.Column("locked_until", sa.DateTime(timezone=True),
                                         comment="锁定截止时间（NULL=未锁定；5 次失败锁 15 分钟）"))

    # 5. seed 四组默认模板（幂等：ON CONFLICT (notify_type) DO NOTHING）
    bind = op.get_bind()
    import json

    for g in _NOTIFY_GROUPS:
        bind.execute(
            sa.text(
                "INSERT INTO pmcp_notify_group "
                "(notify_type, group_name, subject_template, body_template, param_descriptions, enabled, inserted_by) "
                "VALUES (:notify_type, :group_name, :subject, :body, :params, 1, 'system') "
                "ON CONFLICT (notify_type) DO NOTHING"
            ).bindparams(
                sa.bindparam("notify_type", g["notify_type"]),
                sa.bindparam("group_name", g["group_name"]),
                sa.bindparam("subject", g["subject_template"]),
                sa.bindparam("body", g["body_template"]),
                sa.bindparam("params", json.dumps(_PARAM_DESCRIPTIONS, ensure_ascii=False),
                             type_=postgresql.JSONB()),
            )
        )


def downgrade() -> None:
    op.drop_column("pmcp_user", "locked_until")
    op.drop_column("pmcp_user", "failed_attempts")
    op.drop_index("ix_notify_outbox_status", table_name="pmcp_notify_outbox")
    op.drop_table("pmcp_notify_outbox")
    op.drop_table("pmcp_notify_group_member")
    op.drop_table("pmcp_notify_group")
