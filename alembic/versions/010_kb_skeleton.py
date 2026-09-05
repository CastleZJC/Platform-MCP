"""010_kb_skeleton — 三期知识库骨架表（V3.0 M6，架构 §19.6 / 计划 6.1）

Revision ID: 010
Revises: 009
Create Date: 2026-09-05

变更内容（V3.0 仅搭骨架，用户确认；三期实现业务逻辑）：
1. pmcp_kb —— 知识库主体：kb_type 二值（personal/shared）+ owner + status
   （值域复用 review 状态机 8 状态，服务层把守，对齐 pmcp_skill.status 惯例）。
2. pmcp_kb_doc —— 文档（源路径 + checksum + 原文内容，三期导入链路）。
3. pmcp_kb_chunk —— 切片：chunking_strategy 记录切片策略（7 种枚举，kb/chunking.py 把守）
   + embedding JSONB（对齐 pmcp_skill_plaza.embedding 惯例：JSONB 规范存储 + 内存余弦
   降级；pgvector 原生列三期按生产环境条件创建，本迁移不建）。
4. pmcp_kb_version —— 版本存档：双语字段同 pmcp_skill_version 惯例
   （readme/report zh+en + audit_snapshot + generated_by，UNIQUE(kb_id, version) 不可篡改）。
5. pmcp_kb_share —— 分享与审核关联（review_status + merge_target_id 合并目标 +
   review_comment 拒绝原因/迭代说明；审核流三期直接挂接 platform_mcp/review/，不另建）。

迁移编号说明：架构 §19.5.8 拆分口径 010=KB（原 008/009 已被组去环境维度/notify
占用后顺延，009 头注见）；本迁移落地后 head=010，F-42 编号一致性终核同步文档。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 知识库主体（personal/shared + owner + review 状态机）
    op.create_table(
        "pmcp_kb",
        sa.Column("kb_code", sa.String(64), nullable=False, comment="知识库编码（唯一）"),
        sa.Column("kb_name", sa.String(128), nullable=False, comment="知识库名称"),
        sa.Column(
            "kb_type",
            sa.String(16),
            server_default="personal",
            nullable=False,
            comment="类型（personal-个人 / shared-专用可分享，架构 §19.6）",
        ),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_user.id", ondelete="SET NULL"),
            comment="所有者用户 ID（个人库归属；shared 库发起人）",
        ),
        sa.Column("description", sa.Text(), comment="描述"),
        sa.Column(
            "status",
            sa.String(16),
            server_default="DRAFT",
            nullable=False,
            comment="状态（值域复用 review 8 状态，三期挂接 platform_mcp/review/ 状态机）",
        ),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        sa.UniqueConstraint("kb_code", name="uq_pmcp_kb_code"),
        sa.CheckConstraint("kb_code <> ''", name="ck_pmcp_kb_code_nonempty"),
        sa.CheckConstraint("kb_name <> ''", name="ck_pmcp_kb_name_nonempty"),
        sa.CheckConstraint(
            "kb_type IN ('personal', 'shared')", name="ck_pmcp_kb_type_domain"
        ),
        sa.CheckConstraint("status <> ''", name="ck_pmcp_kb_status_nonempty"),
        comment="知识库主体（V3.0 M6 骨架，三期实现，架构 §19.6）",
    )

    # 2. 文档
    op.create_table(
        "pmcp_kb_doc",
        sa.Column(
            "kb_id",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_kb.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属知识库 ID",
        ),
        sa.Column("doc_name", sa.String(256), nullable=False, comment="文档名称/标题"),
        sa.Column("source_path", sa.Text(), comment="源文件存储路径（三期导入链路）"),
        sa.Column("checksum", sa.String(64), comment="源文件 SHA-256"),
        sa.Column("content", sa.Text(), comment="文档原文内容"),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        sa.CheckConstraint("doc_name <> ''", name="ck_pmcp_kb_doc_name_nonempty"),
        comment="知识库文档（V3.0 M6 骨架）",
    )
    op.create_index("ix_kb_doc_kb_id", "pmcp_kb_doc", ["kb_id"])

    # 3. 切片（切片策略 + embedding JSONB；pgvector 原生列三期条件创建）
    op.create_table(
        "pmcp_kb_chunk",
        sa.Column(
            "doc_id",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_kb_doc.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属文档 ID",
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="文档内切片序号（从 0 起）"),
        sa.Column(
            "chunking_strategy",
            sa.String(32),
            nullable=False,
            comment="切片策略（7 种枚举，值域由 platform_mcp/kb/chunking.py 把守，架构 §19.6）",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="切片文本"),
        sa.Column(
            "embedding",
            postgresql.JSONB(),
            comment="切片语义向量（BGE-M3 / 降级哈希；JSONB 存储 + 内存余弦，同 plaza 惯例）",
        ),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        sa.UniqueConstraint("doc_id", "chunk_index", name="uq_pmcp_kb_chunk_doc_idx"),
        sa.CheckConstraint("chunking_strategy <> ''", name="ck_pmcp_kb_chunk_strategy_nonempty"),
        comment="知识库切片（V3.0 M6 骨架，RAG 检索单元）",
    )

    # 4. 版本存档（双语字段同 pmcp_skill_version 惯例，不可篡改）
    op.create_table(
        "pmcp_kb_version",
        sa.Column(
            "kb_id",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_kb.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属知识库 ID",
        ),
        sa.Column("version", sa.String(32), nullable=False, comment="版本号（如 0.1.0）"),
        sa.Column("checksum", sa.String(64), comment="该版本内容 SHA-256"),
        sa.Column("readme_zh", sa.Text(), comment="中文说明存档"),
        sa.Column("readme_en", sa.Text(), comment="英文说明存档"),
        sa.Column("report_zh", sa.Text(), comment="中文审核报告存档"),
        sa.Column("report_en", sa.Text(), comment="英文审核报告存档"),
        sa.Column("audit_snapshot", postgresql.JSONB(), comment="该版本审计快照"),
        sa.Column(
            "generated_by",
            sa.String(16),
            comment="产物来源（template/model/external，同 Skill 版本表惯例）",
        ),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        sa.UniqueConstraint("kb_id", "version", name="uq_pmcp_kb_version_kb_ver"),
        sa.CheckConstraint("version <> ''", name="ck_pmcp_kb_version_nonempty"),
        comment="知识库版本化双语存档（V3.0 M6 骨架，同 Skill 版本表惯例）",
    )

    # 5. 分享与审核关联（审核流三期直接挂接 platform_mcp/review/）
    op.create_table(
        "pmcp_kb_share",
        sa.Column(
            "kb_id",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_kb.id", ondelete="CASCADE"),
            nullable=False,
            comment="发起分享的知识库 ID",
        ),
        sa.Column(
            "shared_by",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_user.id", ondelete="SET NULL"),
            comment="发起分享的用户 ID",
        ),
        sa.Column(
            "review_status",
            sa.String(16),
            nullable=False,
            comment="分享审核状态（PENDING_REVIEW/APPROVED/MERGED/REJECTED/WITHDRAWN 子集，review 服务把守）",
        ),
        sa.Column(
            "merge_target_id",
            sa.BigInteger(),
            sa.ForeignKey("pmcp_kb.id", ondelete="SET NULL"),
            comment="合并目标知识库 ID（admin 合并到已有 shared 库时填写）",
        ),
        sa.Column("review_comment", sa.Text(), comment="审核意见（拒绝原因/迭代说明）"),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(64)),
        sa.Column("updated_by", sa.String(64)),
        sa.CheckConstraint("review_status <> ''", name="ck_pmcp_kb_share_status_nonempty"),
        comment="知识库分享与审核关联（V3.0 M6 骨架，审核流复用 platform_mcp/review/）",
    )
    op.create_index("ix_kb_share_kb_id", "pmcp_kb_share", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_share_kb_id", table_name="pmcp_kb_share")
    op.drop_table("pmcp_kb_share")
    op.drop_table("pmcp_kb_version")
    op.drop_table("pmcp_kb_chunk")
    op.drop_index("ix_kb_doc_kb_id", table_name="pmcp_kb_doc")
    op.drop_table("pmcp_kb_doc")
    op.drop_table("pmcp_kb")
