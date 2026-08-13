"""003_phase2_tables_and_skill_extensions — 二期新增表 + pmcp_skill 扩展字段

Revision ID: 003
Revises: 002
Create Date: 2026-08-11

新增 6 张表：
- pmcp_datasource_group（数据源组）
- pmcp_server_group（服务器组）
- pmcp_datasource_group_member（数据源组成员）
- pmcp_server_group_member（服务器组成员）
- pmcp_user_group（用户-组关联）
- pmcp_skill_audit_report（Skill 审计报告）

pmcp_skill 扩展 7 列：
- source_path TEXT
- source_checksum VARCHAR(64)
- source_format VARCHAR(10)
- version VARCHAR(32)
- audit_status VARCHAR(16)
- audit_result JSONB
- readme_generated BOOLEAN
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================== pmcp_skill 扩展字段 ====================
    op.add_column("pmcp_skill", sa.Column("source_path", sa.Text(), nullable=True, comment="解压后包存储路径"))
    op.add_column("pmcp_skill", sa.Column("source_checksum", sa.String(64), nullable=True, comment="上传包 SHA-256"))
    op.add_column("pmcp_skill", sa.Column("source_format", sa.String(10), nullable=True, comment="包格式(7z/zip)"))
    op.add_column("pmcp_skill", sa.Column("version", sa.String(32), nullable=True, comment="Skill 版本"))
    op.add_column("pmcp_skill", sa.Column("audit_status", sa.String(16), nullable=True, comment="审计状态(pending/passed/failed/warning)"))
    op.add_column("pmcp_skill", sa.Column("audit_result", postgresql.JSONB(), nullable=True, comment="审计摘要（规则命中数、严重级别分布）"))
    op.add_column("pmcp_skill", sa.Column("readme_generated", sa.Boolean(), nullable=True, comment="是否自动生成了 README.md"))

    # ==================== pmcp_datasource_group ====================
    op.create_table(
        "pmcp_datasource_group",
        sa.Column("group_name", sa.String(length=128), nullable=False, comment="组名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="组描述"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="数据源组",
    )

    # ==================== pmcp_server_group ====================
    op.create_table(
        "pmcp_server_group",
        sa.Column("group_name", sa.String(length=128), nullable=False, comment="组名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="组描述"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="服务器组",
    )

    # ==================== pmcp_datasource_group_member ====================
    op.create_table(
        "pmcp_datasource_group_member",
        sa.Column("group_id", sa.BigInteger(), nullable=False, comment="数据源组ID"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源ID"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["datasource_id"], ["pmcp_datasource.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["pmcp_datasource_group.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="数据源组成员",
    )
    op.create_index("idx_ds_group_member_group_id", "pmcp_datasource_group_member", ["group_id"])
    op.create_index("idx_ds_group_member_datasource_id", "pmcp_datasource_group_member", ["datasource_id"])

    # ==================== pmcp_server_group_member ====================
    op.create_table(
        "pmcp_server_group_member",
        sa.Column("group_id", sa.BigInteger(), nullable=False, comment="服务器组ID"),
        sa.Column("server_id", sa.BigInteger(), nullable=False, comment="服务器ID"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["pmcp_server_group.id"]),
        sa.ForeignKeyConstraint(["server_id"], ["pmcp_server.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="服务器组成员",
    )
    op.create_index("idx_srv_group_member_group_id", "pmcp_server_group_member", ["group_id"])
    op.create_index("idx_srv_group_member_server_id", "pmcp_server_group_member", ["server_id"])

    # ==================== pmcp_user_group ====================
    op.create_table(
        "pmcp_user_group",
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("group_type", sa.String(length=32), nullable=False, comment="组类型(datasource/server)"),
        sa.Column("group_id", sa.BigInteger(), nullable=False, comment="组ID(datasource_group.id/server_group.id)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="用户-组关联",
    )
    op.create_index("idx_user_group_user_id", "pmcp_user_group", ["user_id"])
    op.create_index("idx_user_group_type_id", "pmcp_user_group", ["group_type", "group_id"])

    # ==================== pmcp_skill_audit_report ====================
    op.create_table(
        "pmcp_skill_audit_report",
        sa.Column("skill_id", sa.BigInteger(), nullable=False, comment="Skill ID"),
        sa.Column("audit_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True, comment="审计时间"),
        sa.Column("auditor", sa.String(length=64), nullable=False, server_default="system", comment="审计者（系统自动为 system）"),
        sa.Column("rule_id", sa.String(length=10), nullable=False, comment="规则编号（如 R1-01）"),
        sa.Column("severity", sa.String(length=10), nullable=False, comment="严重程度(critical/warning/suggestion)"),
        sa.Column("file_path", sa.String(length=512), nullable=True, comment="违规文件相对路径"),
        sa.Column("line_number", sa.Integer(), nullable=True, comment="违规行号（0 表示文件级）"),
        sa.Column("description", sa.Text(), nullable=True, comment="问题描述"),
        sa.Column("suggestion", sa.Text(), nullable=True, comment="修复建议"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["pmcp_skill.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Skill 审计报告",
    )
    op.create_index("idx_audit_report_skill_id", "pmcp_skill_audit_report", ["skill_id"])


def downgrade() -> None:
    # Drop audit report
    op.drop_index("idx_audit_report_skill_id", table_name="pmcp_skill_audit_report")
    op.drop_table("pmcp_skill_audit_report")

    # Drop user-group
    op.drop_index("idx_user_group_type_id", table_name="pmcp_user_group")
    op.drop_index("idx_user_group_user_id", table_name="pmcp_user_group")
    op.drop_table("pmcp_user_group")

    # Drop server group members
    op.drop_index("idx_srv_group_member_server_id", table_name="pmcp_server_group_member")
    op.drop_index("idx_srv_group_member_group_id", table_name="pmcp_server_group_member")
    op.drop_table("pmcp_server_group_member")

    # Drop server group
    op.drop_table("pmcp_server_group")

    # Drop datasource group members
    op.drop_index("idx_ds_group_member_datasource_id", table_name="pmcp_datasource_group_member")
    op.drop_index("idx_ds_group_member_group_id", table_name="pmcp_datasource_group_member")
    op.drop_table("pmcp_datasource_group_member")

    # Drop datasource group
    op.drop_table("pmcp_datasource_group")

    # Drop pmcp_skill extension columns
    op.drop_column("pmcp_skill", "readme_generated")
    op.drop_column("pmcp_skill", "audit_result")
    op.drop_column("pmcp_skill", "audit_status")
    op.drop_column("pmcp_skill", "version")
    op.drop_column("pmcp_skill", "source_format")
    op.drop_column("pmcp_skill", "source_checksum")
    op.drop_column("pmcp_skill", "source_path")