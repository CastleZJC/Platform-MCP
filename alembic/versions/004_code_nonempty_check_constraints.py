"""004_code_nonempty_check_constraints — 编码列非空串 CHECK 约束

Revision ID: 004
Revises: 003
Create Date: 2026-08-14

BUG20260814134000 修复：server_code / datasource_code 仅 NOT NULL 无法拦截空串
（PostgreSQL 中 '' ≠ NULL），新增 CHECK 约束补齐数据库端防御。

上线前置检查（预期 0 行，否则约束创建失败需先清洗）：
    SELECT id FROM pmcp_server WHERE server_code = '';
    SELECT id FROM pmcp_datasource WHERE datasource_code = '';
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_pmcp_server_server_code_nonempty", "pmcp_server", "server_code <> ''")
    op.create_check_constraint(
        "ck_pmcp_datasource_datasource_code_nonempty", "pmcp_datasource", "datasource_code <> ''"
    )


def downgrade() -> None:
    op.drop_constraint("ck_pmcp_datasource_datasource_code_nonempty", "pmcp_datasource", type_="check")
    op.drop_constraint("ck_pmcp_server_server_code_nonempty", "pmcp_server", type_="check")
