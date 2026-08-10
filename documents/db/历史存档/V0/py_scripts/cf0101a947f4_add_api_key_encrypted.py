"""add key_encrypted column to pmcp_api_key

Revision ID: cf0101a947f4
Revises: ce0101a947f3
Create Date: 2026-06-17

为 admin reveal 明文 Key 支持，新增 key_encrypted 列存 AES 加密后的明文。
- 新生成的 Key 同时写 key_hash（校验用）+ key_encrypted（admin reveal 用）
- 历史 Key 的 key_encrypted 为 NULL，admin reveal 时提示需 reset
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cf0101a947f4"
down_revision: Union[str, None] = "ce0101a947f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pmcp_api_key",
        sa.Column(
            "key_encrypted",
            sa.String(512),
            nullable=True,
            comment="AES 加密后的明文 Key，用于 admin reveal",
        ),
    )


def downgrade() -> None:
    op.drop_column("pmcp_api_key", "key_encrypted")
