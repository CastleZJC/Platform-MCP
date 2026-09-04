"""006_skill_lifecycle_plaza_version_blacklist — V3.0 M2 Skill 生命周期表

Revision ID: 006
Revises: 005
Create Date: 2026-09-03

变更内容（技术架构说明文档 §19.5.3 / §19.5.8）：
1. pmcp_skill_plaza：广场公共池（独立 version 链 + involve_flags + uploader_id + iteration_note）
   —— embedding 列（BGE-M3 语义搜索）按 §19.5.8 留待 migration 007 追加，本迁移不建。
2. pmcp_skill_version：版本化双语存档（readme_zh/en + report_zh/en + audit_snapshot + generated_by）
   —— UNIQUE(skill_id, version) + version 非空 CHECK，版本不可篡改（F-28）。
3. pmcp_skill_blacklist：黑名单（user_id + target_plaza_id/target_skill_id）
   —— 双 UNIQUE + "至少一个目标" CHECK（F-34）。
4. pmcp_skill 加列：plaza_id(FK→pmcp_skill_plaza, SET NULL) / origin(ORIGINAL|PLAZA) / share_status(unshared|shared)
   / review_comment(最近一次审核意见——admin approve/merge/reject 决策，owner 可见，M5 邮件 {{reason}} 源)。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 广场公共池（embedding 列留待 007，见架构 §19.5.8）
    op.create_table(
        "pmcp_skill_plaza",
        sa.Column("skill_code", sa.String(length=64), nullable=False, comment="广场 Skill 编码"),
        sa.Column("skill_name", sa.String(length=128), nullable=False, comment="广场 Skill 名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="Skill 描述"),
        sa.Column("version", sa.String(length=32), nullable=True, comment="当前发布版本（独立 version 链）"),
        sa.Column("uploader_id", sa.BigInteger(), nullable=True, comment="分享者用户 ID"),
        sa.Column("involve_flags", postgresql.JSONB(), nullable=True, comment="涉库/涉服务器标记（audit R2/R3 派生，M3）"),
        sa.Column("iteration_note", sa.Text(), nullable=True, comment="admin 合并迭代说明"),
        sa.Column("source_path", sa.Text(), nullable=True, comment="广场副本包存储路径"),
        sa.Column("source_checksum", sa.String(length=64), nullable=True, comment="广场副本包 SHA-256"),
        sa.Column("status", sa.String(length=16), server_default="PUBLISHED", nullable=False, comment="广场状态(PUBLISHED/DISABLED)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["uploader_id"], ["pmcp_user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("skill_code", name="uq_pmcp_skill_plaza_skill_code"),
        comment="Skill 广场公共池（独立于个人库，V3.0）",
    )

    # 2. 版本化双语存档
    op.create_table(
        "pmcp_skill_version",
        sa.Column("skill_id", sa.BigInteger(), nullable=False, comment="所属 Skill ID"),
        sa.Column("version", sa.String(length=32), nullable=False, comment="版本号（如 0.1.0）"),
        sa.Column("checksum", sa.String(length=64), nullable=True, comment="该版本源码包 SHA-256"),
        sa.Column("readme_zh", sa.Text(), nullable=True, comment="中文 README（存档不可篡改）"),
        sa.Column("readme_en", sa.Text(), nullable=True, comment="英文 README"),
        sa.Column("report_zh", sa.Text(), nullable=True, comment="中文审核报告（合规规则命中 + 广场比对结论）"),
        sa.Column("report_en", sa.Text(), nullable=True, comment="英文审核报告"),
        sa.Column("audit_snapshot", postgresql.JSONB(), nullable=True, comment="该版本审计快照（规则命中摘要）"),
        sa.Column("generated_by", sa.String(length=16), nullable=True, comment="产物来源(template/model，架构 §19.5.6)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["skill_id"], ["pmcp_skill.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("skill_id", "version", name="uq_pmcp_skill_version_skill_ver"),
        sa.CheckConstraint("version <> ''", name="ck_pmcp_skill_version_nonempty"),
        comment="Skill 版本化双语存档（README/审核报告/审计快照，V3.0 M2）",
    )
    op.create_index("idx_pmcp_skill_version_skill_id", "pmcp_skill_version", ["skill_id"])

    # 3. 黑名单
    op.create_table(
        "pmcp_skill_blacklist",
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="屏蔽发起用户 ID"),
        sa.Column("target_plaza_id", sa.BigInteger(), nullable=True, comment="屏蔽的广场 Skill ID"),
        sa.Column("target_skill_id", sa.BigInteger(), nullable=True, comment="屏蔽的个人 Skill ID"),
        sa.Column("reason", sa.String(length=512), nullable=True, comment="屏蔽原因（可选）"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_plaza_id"], ["pmcp_skill_plaza.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_skill_id"], ["pmcp_skill.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "target_plaza_id", name="uq_pmcp_skill_blacklist_plaza"),
        sa.UniqueConstraint("user_id", "target_skill_id", name="uq_pmcp_skill_blacklist_skill"),
        sa.CheckConstraint(
            "target_plaza_id IS NOT NULL OR target_skill_id IS NOT NULL",
            name="ck_pmcp_skill_blacklist_has_target",
        ),
        comment="Skill 黑名单（用户屏蔽，双端不可见仅黑名单页可见，V3.0 M2）",
    )
    op.create_index("idx_pmcp_skill_blacklist_user_id", "pmcp_skill_blacklist", ["user_id"])

    # 4. pmcp_skill 加列：plaza_id / origin / share_status
    op.add_column("pmcp_skill", sa.Column("plaza_id", sa.BigInteger(), nullable=True, comment="关联广场副本 ID"))
    op.create_foreign_key(
        "fk_pmcp_skill_plaza_id", "pmcp_skill", "pmcp_skill_plaza",
        ["plaza_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(
        "pmcp_skill",
        sa.Column("origin", sa.String(length=16), server_default="ORIGINAL", nullable=False, comment="来源(ORIGINAL 原创/PLAZA 广场复制)"),
    )
    op.add_column(
        "pmcp_skill",
        sa.Column("share_status", sa.String(length=16), server_default="unshared", nullable=False, comment="分享状态(unshared 未分享/shared 已入广场)"),
    )
    op.create_check_constraint("ck_pmcp_skill_origin", "pmcp_skill", "origin IN ('ORIGINAL', 'PLAZA')")
    op.create_check_constraint("ck_pmcp_skill_share_status", "pmcp_skill", "share_status IN ('unshared', 'shared')")
    op.create_index("idx_pmcp_skill_plaza_id", "pmcp_skill", ["plaza_id"])
    # review_comment：owner 可见的最近审核意见（拒绝原因/迭代说明）。审计日志因 F-40「非 admin 仅见自己」
    # 无法向 owner 暴露 admin 决策，故独立持久化；同时作为 M5 skill_review 邮件 {{reason}} 参数源。
    op.add_column(
        "pmcp_skill",
        sa.Column("review_comment", sa.Text(), nullable=True, comment="最近一次审核意见(admin approve/merge/reject 决策，owner 可见)"),
    )


def downgrade() -> None:
    # 逆序回滚：先拆 pmcp_skill 新列（review_comment/索引/CHECK/列/FK），再 DROP 三表（blacklist 依赖 plaza+skill）
    op.drop_column("pmcp_skill", "review_comment")
    op.drop_index("idx_pmcp_skill_plaza_id", table_name="pmcp_skill")
    op.drop_constraint("ck_pmcp_skill_share_status", "pmcp_skill", type_="check")
    op.drop_constraint("ck_pmcp_skill_origin", "pmcp_skill", type_="check")
    op.drop_column("pmcp_skill", "share_status")
    op.drop_column("pmcp_skill", "origin")
    op.drop_constraint("fk_pmcp_skill_plaza_id", "pmcp_skill", type_="foreignkey")
    op.drop_column("pmcp_skill", "plaza_id")

    op.drop_index("idx_pmcp_skill_blacklist_user_id", table_name="pmcp_skill_blacklist")
    op.drop_table("pmcp_skill_blacklist")
    op.drop_index("idx_pmcp_skill_version_skill_id", table_name="pmcp_skill_version")
    op.drop_table("pmcp_skill_version")
    op.drop_table("pmcp_skill_plaza")
