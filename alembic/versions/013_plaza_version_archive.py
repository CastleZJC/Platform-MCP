"""pmcp_plaza_version 广场版本归档表

广场 Skill 历史版本链（2026-09-08，用户裁决：文件级版本管理仅限广场 Skill；个人 /
装饰器系统 Skill 仅保留最新版）：approve 新增入广场 / merge 迭代时全量快照到
``{upload_dir}/_plaza_versions/{plaza_id}/{version}/`` + 文件清单（path/size/sha256）
落库；UNIQUE(plaza_id, version) 同版本重发布覆盖、不同版本累积为不可变历史；
存量广场由 Web 启动 ``backfill_plaza_versions`` 幂等补一版（无文件 I/O 进迁移）。
手工回退经 ``scripts/_rollback_plaza_version.py``（快照复制回 _plaza/{id} + DB 回写 + 审计）。

Revision ID: 013
Revises: 012
Create Date: 2026-09-08
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pmcp_plaza_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("snapshot_path", sa.Text(), nullable=True),
        sa.Column("file_manifest", JSONB(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("audit_snapshot", JSONB(), nullable=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("inserted_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["plaza_id"], ["pmcp_skill_plaza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plaza_id", "version", name="uq_pmcp_plaza_version_plaza_ver"),
        comment="Skill 广场版本归档（仅广场 Skill 版本管理；个人/系统 Skill 仅最新版）",
    )
    op.create_index("ix_pmcp_plaza_version_plaza_id", "pmcp_plaza_version", ["plaza_id"])


def downgrade() -> None:
    op.drop_index("ix_pmcp_plaza_version_plaza_id", table_name="pmcp_plaza_version")
    op.drop_table("pmcp_plaza_version")
