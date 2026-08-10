"""drop audit dead columns

Revision ID: cg0101a947f5
Revises: cf0101a947f4
Create Date: 2026-06-22 15:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "cg0101a947f5"
down_revision = "cf0101a947f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("pmcp_audit_log", "start_time")
    op.drop_column("pmcp_audit_log", "end_time")


def downgrade() -> None:
    op.add_column("pmcp_audit_log", sa.Column("end_time", sa.DateTime(timezone=True)))
    op.add_column("pmcp_audit_log", sa.Column("start_time", sa.DateTime(timezone=True)))
