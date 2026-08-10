"""drop dead columns

Revision ID: cb0101a947f0
Revises: cb0101a947ef
Create Date: 2026-06-12 13:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "cb0101a947f0"
down_revision = "cb0101a947ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("pmcp_datasource", "connection_string")
    op.drop_column("pmcp_datasource", "extra_config")
    op.drop_column("pmcp_user", "remark")


def downgrade() -> None:
    op.add_column("pmcp_user", sa.Column("remark", sa.String(512)))
    op.add_column("pmcp_datasource", sa.Column("extra_config", sa.dialects.postgresql.JSONB))
    op.add_column("pmcp_datasource", sa.Column("connection_string", sa.String(512)))
