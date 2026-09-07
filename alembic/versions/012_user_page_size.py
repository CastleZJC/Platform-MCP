"""pmcp_user 个人每页条数列

V3.0 分页统一（2026-09-07）：个人「每页条数」偏好（5/10/20/50/75/100，配套运行时
配置键 sys.default_page_size）。存量用户回填默认 20 —— 此后 sys.default_page_size
调整仅影响新创建用户（seed），现有用户不受影响。

Revision ID: 012
Revises: 011
Create Date: 2026-09-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pmcp_user",
        sa.Column(
            "page_size",
            sa.Integer(),
            nullable=True,
            comment="个人每页条数(5/10/20/50/75/100，空=创建时系统默认)",
        ),
    )
    op.execute("UPDATE pmcp_user SET page_size = 20 WHERE page_size IS NULL")


def downgrade() -> None:
    op.drop_column("pmcp_user", "page_size")
