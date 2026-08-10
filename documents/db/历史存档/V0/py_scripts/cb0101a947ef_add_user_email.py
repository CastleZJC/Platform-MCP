"""add user email

Revision ID: cb0101a947ef
Revises: cb0101a947ee
Create Date: 2026-06-12 10:01:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "cb0101a947ef"
down_revision = "cb0101a947ee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pmcp_user", sa.Column("email", sa.String(128), nullable=True, comment="邮箱地址"))
    op.add_column("pmcp_datasource", sa.Column("remark", sa.String(512), nullable=True, comment="备注"))


def downgrade() -> None:
    op.drop_column("pmcp_datasource", "remark")
    op.drop_column("pmcp_user", "email")
