"""002_drop_unused_permission_tables — 二期清理：DROP 4 张 V1.0 遗留空表

Revision ID: 002
Revises: 001
Create Date: 2026-08-11

移除以下空表（无 seed 数据、无业务代码引用）：
- pmcp_permission（细粒度权限定义，被分组管理替代）
- pmcp_role_permission（角色-权限关联，被分组管理替代）
- pmcp_datasource_permission（数据源权限，被数据源组替代）
- pmcp_server_permission（服务器权限，被服务器组替代）

对应 ORM 模型已在代码中移除：
- PmcpPermission, PmcpRolePermission (auth/models.py)
- PmcpDatasourcePermission (datasource/models.py)
- PmcpServerPermission (server/models.py)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先删有外键依赖的子表，再删父表
    # pmcp_server_permission → 依赖 pmcp_server, pmcp_user, pmcp_role
    op.drop_index("idx_pmcp_server_permission_server_id", table_name="pmcp_server_permission")
    op.drop_table("pmcp_server_permission")

    # pmcp_datasource_permission → 依赖 pmcp_datasource, pmcp_user, pmcp_role
    op.drop_index("idx_pmcp_datasource_permission_datasource_id", table_name="pmcp_datasource_permission")
    op.drop_index("idx_pmcp_datasource_permission_user_id", table_name="pmcp_datasource_permission")
    op.drop_index("idx_pmcp_datasource_permission_role_id", table_name="pmcp_datasource_permission")
    op.drop_table("pmcp_datasource_permission")

    # pmcp_role_permission → 依赖 pmcp_role, pmcp_permission
    op.drop_index("idx_pmcp_role_permission_role_id", table_name="pmcp_role_permission")
    op.drop_index("idx_pmcp_role_permission_permission_id", table_name="pmcp_role_permission")
    op.drop_table("pmcp_role_permission")

    # pmcp_permission → 无外键依赖（子表已删）
    op.drop_index("un_pmcp_permission_permission_code", table_name="pmcp_permission")
    op.drop_table("pmcp_permission")


def downgrade() -> None:
    # 重建 pmcp_permission
    op.create_table(
        "pmcp_permission",
        sa.Column("permission_name", sa.String(length=128), nullable=False, comment="权限名称"),
        sa.Column("permission_code", sa.String(length=128), nullable=False, comment="权限标识"),
        sa.Column("resource_type", sa.String(length=64), nullable=True, comment="资源类型(menu/button/api)"),
        sa.Column("resource_path", sa.String(length=256), nullable=True, comment="资源路径"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True, comment="父权限ID"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=True, comment="排序"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("permission_code", name="un_pmcp_permission_permission_code"),
        comment="权限定义",
    )

    # 重建 pmcp_role_permission
    op.create_table(
        "pmcp_role_permission",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["permission_id"], ["pmcp_permission.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="角色权限关系",
    )
    op.create_index("idx_pmcp_role_permission_role_id", "pmcp_role_permission", ["role_id"])
    op.create_index("idx_pmcp_role_permission_permission_id", "pmcp_role_permission", ["permission_id"])

    # 重建 pmcp_datasource_permission
    op.create_table(
        "pmcp_datasource_permission",
        sa.Column("datasource_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="授权用户"),
        sa.Column("role_id", sa.BigInteger(), nullable=True, comment="授权角色"),
        sa.Column("permission_type", sa.String(length=32), nullable=False, comment="权限类型(query/manage)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["datasource_id"], ["pmcp_datasource.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="数据源权限关系",
    )
    op.create_index("idx_pmcp_datasource_permission_datasource_id", "pmcp_datasource_permission", ["datasource_id"])
    op.create_index("idx_pmcp_datasource_permission_user_id", "pmcp_datasource_permission", ["user_id"])
    op.create_index("idx_pmcp_datasource_permission_role_id", "pmcp_datasource_permission", ["role_id"])

    # 重建 pmcp_server_permission
    op.create_table(
        "pmcp_server_permission",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="授权用户"),
        sa.Column("role_id", sa.BigInteger(), nullable=True, comment="授权角色"),
        sa.Column("permission_type", sa.String(length=32), nullable=False, comment="权限类型(exec/upload/download/manage)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["pmcp_server.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="服务器权限关系",
    )
    op.create_index("idx_pmcp_server_permission_server_id", "pmcp_server_permission", ["server_id"])