"""add pmcp_api_key table

Revision ID: ce0101a947f3
Revises: cd0101a947f2
Create Date: 2026-06-17

API Key 认证表，支持 MCP 层用户级身份校验。
Key 格式: pmcp_ + secrets.token_urlsafe(32)，SHA-256 哈希存储。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ce0101a947f3"
down_revision: Union[str, None] = "cd0101a947f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pmcp_api_key",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="所属用户"),
        sa.Column("key_hash", sa.String(128), nullable=False, comment="SHA-256 哈希"),
        sa.Column("key_prefix", sa.String(16), nullable=False, comment="前8位用于识别"),
        sa.Column("description", sa.String(255), nullable=True, comment="备注"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1", comment="1=活跃 0=已撤销"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True, comment="最近使用时间"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="过期时间"),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pmcp_api_key_user_id", "pmcp_api_key", ["user_id"])
    op.create_unique_constraint("un_pmcp_api_key_key_hash", "pmcp_api_key", ["key_hash"])


def downgrade() -> None:
    op.drop_table("pmcp_api_key")
