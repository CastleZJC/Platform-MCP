"""Skill 生命周期增强（迭代通知 / merge 工作台 / 版本链 / 多语言补足）

1. pmcp_skill.copied_from_plaza_version VARCHAR(64) —— add-to-my 复制时记录来源广场版本
   （老版本 3-way merge 的 base）；存量回填 origin=PLAZA 行 ← pmcp_skill_plaza.version。
2. pmcp_skill_version.readme_extra / report_extra JSONB —— 多语言补足产物
   （{locale: text}；tier：template < model < external，本地永不覆盖 external）。
3. pmcp_plaza_version.source_version VARCHAR(64) —— 提交人版本存档（广场版本自增 +patch，
   提交人版本不再透传为广场版本）。
4. pmcp_plaza_merge 新表（slim）—— merge 工作台：build 临时包 _plaza_merge/{plaza_id}/{token}/
   + 冲突清单 admin 裁决 + publish（升广场新版）/discard 状态机。
5. notify skill_review 默认模板补 {{skill_id}}/{{submitter}}/{{version}} 参数
   （WHERE 等于默认文案才更新，保护用户自定义；param_descriptions 仅增量合并新键）。

Revision ID: 014
Revises: 013
Create Date: 2026-09-10
"""

import json
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels = None
depends_on = None

_SR_OLD_SUBJECT = "【Platform-MCP】Skill 审核事件：{{resource}}（{{action}}）"
_SR_OLD_BODY = (
    "操作人：{{user}}\n"
    "Skill：{{resource}}\n"
    "动作：{{action}}\n"
    "时间：{{time}}\n"
    "说明：{{reason}}{{iteration_note}}\n"
    "\n-- Platform-MCP Skill 审核流（提审/审核结果/撤回自动触达）"
)
_SR_NEW_BODY = (
    "操作人：{{user}}\n"
    "提交人：{{submitter}}\n"
    "Skill ID：{{skill_id}}\n"
    "Skill：{{resource}}\n"
    "版本：{{version}}\n"
    "动作：{{action}}\n"
    "时间：{{time}}\n"
    "说明：{{reason}}{{iteration_note}}\n"
    "\n-- Platform-MCP Skill 审核流（提审/审核结果/撤回自动触达）"
)
_SR_EXTRA_PARAMS = json.dumps(
    {
        "skill_id": "Skill ID（个人库行）",
        "submitter": "提交人用户名",
        "version": "Skill 版本",
    },
    ensure_ascii=False,
)


def upgrade() -> None:
    # 1. 个人 Skill 记录复制来源广场版本（3-way merge base）
    op.add_column(
        "pmcp_skill",
        sa.Column("copied_from_plaza_version", sa.String(64), nullable=True,
                  comment="复制来源广场版本（add-to-my 记录，3-way merge base）"),
    )
    op.execute(
        sa.text(
            "UPDATE pmcp_skill s SET copied_from_plaza_version = p.version "
            "FROM pmcp_skill_plaza p "
            "WHERE s.plaza_id = p.id AND s.origin = 'PLAZA'"
        )
    )

    # 2. 版本存档多语言补足产物
    op.add_column(
        "pmcp_skill_version",
        sa.Column("readme_extra", JSONB(), nullable=True,
                  comment="多语言 README 补足（{locale: text}，tier template<model<external）"),
    )
    op.add_column(
        "pmcp_skill_version",
        sa.Column("report_extra", JSONB(), nullable=True,
                  comment="多语言审核报告补足（{locale: text}，tier template<model<external）"),
    )

    # 3. 广场版本归档记提交人来源版本
    op.add_column(
        "pmcp_plaza_version",
        sa.Column("source_version", sa.String(64), nullable=True,
                  comment="提交人版本（来源版本，不透传为广场版本）"),
    )

    # 4. merge 工作台 slim 表
    op.create_table(
        "pmcp_plaza_merge",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("merge_token", sa.String(64), nullable=False,
                  comment="合并工作台令牌（build 返回，get_skill_file/publish 引用）"),
        sa.Column("plaza_id", sa.BigInteger(), nullable=False,
                  comment="目标广场 Skill ID"),
        sa.Column("source_skills", JSONB(), nullable=False,
                  comment="来源个人 Skill [{skill_id, role: primary|secondary}]"),
        sa.Column("base_version", sa.String(64), nullable=True,
                  comment="3-way 基线版本（copied_from_plaza_version 或 admin 指定）"),
        sa.Column("new_version", sa.String(64), nullable=True,
                  comment="目标发布版本"),
        sa.Column("conflicts", JSONB(), nullable=True,
                  comment="冲突清单 [{path, candidates, resolution}]"),
        sa.Column("audit_summary", JSONB(), nullable=True,
                  comment="14 条审计预跑摘要（build 时）"),
        sa.Column("snapshot_path", sa.String(512), nullable=True,
                  comment="临时合并包目录（{upload_dir}/_plaza_merge/{plaza_id}/{token}）"),
        sa.Column("status", sa.String(16), server_default="BUILT", nullable=False,
                  comment="状态(BUILT 已构建/PUBLISHED 已发布/DISCARDED 已丢弃)"),
        sa.Column("created_by", sa.String(64), nullable=False,
                  comment="创建 admin 用户名"),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("inserted_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["plaza_id"], ["pmcp_skill_plaza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merge_token", name="uq_pmcp_plaza_merge_token"),
        comment="广场 merge 工作台（文件级并集 + admin 裁决，2026-09-10）",
    )
    op.create_index("ix_pmcp_plaza_merge_plaza_id", "pmcp_plaza_merge", ["plaza_id"])

    # 5. skill_review 默认模板补参数（仅默认文案行；param_descriptions 增量合并保留自定义）
    #    注：:extra_params 后不可用 ::jsonb 短 cast（SQLAlchemy bindparam 解析视 :name: 为
    #    cast 而非参数），统一 CAST(:param AS jsonb) 写法。
    op.execute(
        sa.text(
            "UPDATE pmcp_notify_group SET body_template = :new_body, "
            "param_descriptions = COALESCE(param_descriptions, '{}'::jsonb) || CAST(:extra_params AS jsonb) "
            "WHERE notify_type = 'skill_review' "
            "AND subject_template = :old_subject AND body_template = :old_body"
        ).bindparams(
            sa.bindparam("new_body", _SR_NEW_BODY),
            sa.bindparam("extra_params", _SR_EXTRA_PARAMS),
            sa.bindparam("old_subject", _SR_OLD_SUBJECT),
            sa.bindparam("old_body", _SR_OLD_BODY),
        )
    )


def downgrade() -> None:
    # 5. 模板回滚（仅新默认文案行；新参数键保留无害，参数描述不回删）
    op.execute(
        sa.text(
            "UPDATE pmcp_notify_group SET body_template = :old_body "
            "WHERE notify_type = 'skill_review' "
            "AND subject_template = :old_subject AND body_template = :new_body"
        ).bindparams(
            sa.bindparam("old_body", _SR_OLD_BODY),
            sa.bindparam("old_subject", _SR_OLD_SUBJECT),
            sa.bindparam("new_body", _SR_NEW_BODY),
        )
    )
    # 4. drop merge 工作台
    op.drop_index("ix_pmcp_plaza_merge_plaza_id", table_name="pmcp_plaza_merge")
    op.drop_table("pmcp_plaza_merge")
    # 3. drop 来源版本列
    op.drop_column("pmcp_plaza_version", "source_version")
    # 2. drop 多语言补足列
    op.drop_column("pmcp_skill_version", "report_extra")
    op.drop_column("pmcp_skill_version", "readme_extra")
    # 1. drop 复制来源版本列
    op.drop_column("pmcp_skill", "copied_from_plaza_version")
