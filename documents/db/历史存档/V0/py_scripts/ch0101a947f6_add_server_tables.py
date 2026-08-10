"""add pmcp_server + pmcp_server_permission tables

Revision ID: ch0101a947f6
Revises: cg0101a947f5
Create Date: 2026-08-07

服务器管理表，支持 Claude Code 通过 skill server 对远端 Linux 服务器
执行 SSH 命令与 SFTP 文件传输。镜像 pmcp_datasource 结构，权限分层
admin（全环境）/ developer（DEV+UAT），PROD 自动升 CRITICAL 走 confirm_token。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ch0101a947f6"
down_revision: Union[str, None] = "cg0101a947f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pmcp_server",
        sa.Column("server_code", sa.String(length=64), nullable=False, comment="服务器编码"),
        sa.Column("server_name", sa.String(length=128), nullable=False, comment="服务器名称"),
        sa.Column("host", sa.String(length=256), nullable=False),
        sa.Column("ssh_port", sa.SmallInteger(), nullable=False, server_default="22", comment="SSH 端口"),
        sa.Column("username", sa.String(length=128), nullable=False, comment="登录用户名"),
        sa.Column("encrypted_password", sa.String(length=512), nullable=True, comment="AES 密文密码（与 ssh_key 二选一）"),
        sa.Column("encrypted_ssh_key", sa.Text(), nullable=True, comment="AES 密文 PEM 私钥（与 password 二选一）"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("max_concurrent", sa.SmallInteger(), server_default="3", nullable=False, comment="同服务器并发 SSH 上限"),
        sa.Column("command_timeout", sa.SmallInteger(), server_default="300", nullable=False, comment="命令超时(秒)"),
        sa.Column("allowed_paths", sa.Text(), nullable=True, comment="JSON 数组：SFTP/upload/download 远端白名单"),
        sa.Column("forbidden_paths", sa.Text(), nullable=True, comment="JSON 数组：远端黑名单"),
        sa.Column("remark", sa.String(length=512), nullable=True, comment="备注"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_code"),
        comment="服务器配置",
    )
    op.create_index("idx_pmcp_server_env_code", "pmcp_server", ["env_code"])

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


def downgrade() -> None:
    op.drop_table("pmcp_server_permission")
    op.drop_index("idx_pmcp_server_env_code", table_name="pmcp_server")
    op.drop_table("pmcp_server")
