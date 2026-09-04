"""plaza embedding 列（BGE-M3 语义搜索）

Revision ID: 007
Revises: 006
Create Date: 2026-09-04

变更内容（技术架构说明文档 §19.5.6 / §19.5.8，计划 M3.2、VNF-02、R-12）：
1. pmcp_skill_plaza.embedding JSONB —— 语义向量的规范存储（BGE-M3 dense 向量或降级哈希向量），
   配合内存余弦为「pgvector 受限」的降级路径（VNF-02，先行验收），无扩展依赖，始终可用。
2. pmcp_skill_plaza.embedding_vec vector(1024) —— pgvector 原生列（DB 侧余弦 <=>），
   仅当目标库可装 vector 扩展时创建（生产可装扩展时启用）；不可用则跳过，
   EmbeddingStore 工厂运行期自动降级到 JSONB+内存余弦（R-12）。

注：迁移编号与架构 §19.5.8 原文（007=notify+embedding 捆绑）按里程碑消费顺序拆分——
M3 独占 007（embedding），M5 notify→008，M6 KB→009；编号一致性于 M6.3（F-42）同步文档。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from loguru import logger
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: BGE-M3 dense 向量维度（架构 §19.5.6）；pgvector 原生列据此定型
_EMBEDDING_DIM = 1024


def _pgvector_available(bind) -> bool:
    """目标库是否可安装 vector 扩展（pg_available_extensions 有记录）。"""
    row = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).first()
    return row is not None


def upgrade() -> None:
    # 1. JSONB 向量列（规范存储 + 内存余弦降级路径，无扩展依赖，始终创建）
    op.add_column(
        "pmcp_skill_plaza",
        sa.Column(
            "embedding",
            postgresql.JSONB(),
            nullable=True,
            comment="Skill 语义向量（BGE-M3 / 降级哈希；JSONB 存储 + 内存余弦，架构 §19.5.6 / VNF-02）",
        ),
    )

    # 2. pgvector 原生列（仅生产可装扩展时；不可用则跳过，运行期 EmbeddingStore 自动降级 JSONB）
    bind = op.get_bind()
    if _pgvector_available(bind):
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        # 用裸 DDL 添加 vector 列，避免引入 pgvector python 包硬依赖（ORM 不声明该列，仅原生 SQL 读写）
        bind.execute(
            sa.text(
                f"ALTER TABLE pmcp_skill_plaza ADD COLUMN embedding_vec vector({_EMBEDDING_DIM})"
            )
        )
        bind.execute(
            sa.text(
                "COMMENT ON COLUMN pmcp_skill_plaza.embedding_vec IS "
                "'pgvector 原生向量列（DB 侧余弦 <=>，架构 §19.5.6）'"
            )
        )
        logger.info("migration 007：pgvector 可用，已创建 embedding_vec vector({})", _EMBEDDING_DIM)
    else:
        logger.info("migration 007：pgvector 不可用，跳过 embedding_vec（EmbeddingStore 降级 JSONB+内存余弦，R-12）")


def downgrade() -> None:
    # embedding_vec 仅在 pgvector 可用时创建；DROP IF EXISTS 兼容两种环境。
    # 不 DROP EXTENSION vector（扩展为库级资源，可能被其他对象依赖）。
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE pmcp_skill_plaza DROP COLUMN IF EXISTS embedding_vec"))
    op.drop_column("pmcp_skill_plaza", "embedding")
