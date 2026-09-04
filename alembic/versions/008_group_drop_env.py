"""008_group_drop_env — 组去环境维度（组与环境正交）

Revision ID: 008
Revises: 007
Create Date: 2026-09-04

变更内容：
1. 跨环境同名组合并：保留 id 最小的组，三类成员并入（ON CONFLICT 去重）
2. 删除被合并的多余组行
3. pmcp_group DROP UNIQUE(env_code, group_name) + DROP env_code → 新增 UNIQUE(group_name)

背景：组只挂资源集合（一个 OA 组可同时含 DEV/UAT/PROD 数据源），
环境管控走资源自身 env_code + 角色双项控制（developer 禁 PROD 等仍由 permission 层执行）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (成员表, 资源列) 三类
_MEMBER_TABLES = (
    ("pmcp_group_user", "user_id"),
    ("pmcp_group_datasource", "datasource_id"),
    ("pmcp_group_server", "server_id"),
)


def _merge_same_name_groups() -> None:
    """同名组（不同 env）成员并入 id 最小的保留组，再删除多余组行。"""
    for table, res_col in _MEMBER_TABLES:
        op.execute(
            f"INSERT INTO {table} (group_id, {res_col}, inserted_by) "
            f"SELECT keep.id, dup_m.{res_col}, 'migration_008' "
            f"FROM {table} dup_m "
            f"JOIN pmcp_group dup_g ON dup_g.id = dup_m.group_id "
            f"JOIN pmcp_group keep ON keep.group_name = dup_g.group_name AND keep.id < dup_g.id "
            f"ON CONFLICT (group_id, {res_col}) DO NOTHING"
        )
    op.execute(
        "DELETE FROM pmcp_group g WHERE EXISTS ("
        "  SELECT 1 FROM pmcp_group k WHERE k.group_name = g.group_name AND k.id < g.id)"
    )


def upgrade() -> None:
    _merge_same_name_groups()
    op.drop_constraint("uq_pmcp_group_env_name", "pmcp_group", type_="unique")
    op.drop_column("pmcp_group", "env_code")
    op.create_unique_constraint("uq_pmcp_group_name", "pmcp_group", ["group_name"])


def downgrade() -> None:
    # 逆转：恢复 env_code（信息已丢失，统一回填 DEV）并重建原唯一约束
    op.drop_constraint("uq_pmcp_group_name", "pmcp_group", type_="unique")
    op.add_column(
        "pmcp_group",
        sa.Column("env_code", sa.String(length=32), nullable=False, server_default="DEV",
                  comment="环境标识(DEV/UAT/PROD)"),
    )
    op.create_unique_constraint("uq_pmcp_group_env_name", "pmcp_group", ["env_code", "group_name"])
