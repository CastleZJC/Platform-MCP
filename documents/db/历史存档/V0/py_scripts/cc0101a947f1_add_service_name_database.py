"""add service_name and database columns to pmcp_datasource

Revision ID: cc0101a947f1
Revises: cb0101a947f0
Create Date: 2026-06-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc0101a947f1"
down_revision: Union[str, None] = "cb0101a947f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pmcp_datasource",
        sa.Column("service_name", sa.String(128), nullable=True, comment="Oracle 服务名"),
    )
    op.add_column(
        "pmcp_datasource",
        sa.Column("database", sa.String(128), nullable=True, comment="MySQL 默认数据库"),
    )


def downgrade() -> None:
    op.drop_column("pmcp_datasource", "database")
    op.drop_column("pmcp_datasource", "service_name")
