"""知识库骨架 ORM 模型（V3.0 M6，架构 §19.6 / migration 010）

五表仅建表与映射，业务逻辑三期实现：
- PmcpKb：主体（personal/shared + owner + status，状态值域复用 review 状态机，
  三期挂接 ``platform_mcp/review/`` 不另建审核流）；
- PmcpKbDoc：文档（源路径 + checksum + 原文）；
- PmcpKbChunk：切片（chunking_strategy 记录 7 策略之一 + embedding JSONB，
  对齐 ``pmcp_skill_plaza.embedding`` 惯例——JSONB 规范存储 + 内存余弦降级，
  pgvector 原生列三期按生产环境条件创建，ORM 不声明）；
- PmcpKbVersion：版本存档（双语字段同 ``pmcp_skill_version`` 惯例，不可篡改）；
- PmcpKbShare：分享与审核关联（merge_target_id 合并目标 + review_comment）。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpKb(BaseModel):
    """知识库主体：personal/shared 二值类型 + owner + review 状态机（三期挂接）。"""

    __tablename__ = "pmcp_kb"

    kb_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="知识库编码（唯一）")
    kb_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="知识库名称")
    kb_type: Mapped[str] = mapped_column(
        String(16), server_default="personal", nullable=False, comment="类型（personal/shared）"
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_user.id", ondelete="SET NULL"), comment="所有者用户 ID"
    )
    description: Mapped[str | None] = mapped_column(Text, comment="描述")
    status: Mapped[str] = mapped_column(
        String(16), server_default="DRAFT", nullable=False, comment="状态（值域复用 review 8 状态）"
    )

    __table_args__ = (
        UniqueConstraint("kb_code", name="uq_pmcp_kb_code"),
        CheckConstraint("kb_code <> ''", name="ck_pmcp_kb_code_nonempty"),
        CheckConstraint("kb_name <> ''", name="ck_pmcp_kb_name_nonempty"),
        CheckConstraint("kb_type IN ('personal', 'shared')", name="ck_pmcp_kb_type_domain"),
        CheckConstraint("status <> ''", name="ck_pmcp_kb_status_nonempty"),
        {"comment": "知识库主体（V3.0 M6 骨架，三期实现，架构 §19.6）"},
    )


class PmcpKbDoc(BaseModel):
    """知识库文档：源路径 + checksum + 原文内容（三期导入链路）。"""

    __tablename__ = "pmcp_kb_doc"

    kb_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_kb.id", ondelete="CASCADE"), nullable=False, comment="所属知识库 ID"
    )
    doc_name: Mapped[str] = mapped_column(String(256), nullable=False, comment="文档名称/标题")
    source_path: Mapped[str | None] = mapped_column(Text, comment="源文件存储路径")
    checksum: Mapped[str | None] = mapped_column(String(64), comment="源文件 SHA-256")
    content: Mapped[str | None] = mapped_column(Text, comment="文档原文内容")

    __table_args__ = (
        CheckConstraint("doc_name <> ''", name="ck_pmcp_kb_doc_name_nonempty"),
        {"comment": "知识库文档（V3.0 M6 骨架）"},
    )


class PmcpKbChunk(BaseModel):
    """切片：RAG 检索单元（切片策略 + embedding，UNIQUE(doc_id, chunk_index)）。"""

    __tablename__ = "pmcp_kb_chunk"

    doc_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_kb_doc.id", ondelete="CASCADE"), nullable=False, comment="所属文档 ID"
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="文档内切片序号（从 0 起）")
    chunking_strategy: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="切片策略（7 种枚举，kb/chunking.py 把守）"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切片文本")
    embedding: Mapped[list | None] = mapped_column(
        JSONB, comment="切片语义向量（BGE-M3 / 降级哈希；JSONB 存储 + 内存余弦）"
    )

    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_pmcp_kb_chunk_doc_idx"),
        CheckConstraint("chunking_strategy <> ''", name="ck_pmcp_kb_chunk_strategy_nonempty"),
        {"comment": "知识库切片（V3.0 M6 骨架，RAG 检索单元）"},
    )


class PmcpKbVersion(BaseModel):
    """版本化双语存档：字段同 pmcp_skill_version 惯例，UNIQUE(kb_id, version) 不可篡改。"""

    __tablename__ = "pmcp_kb_version"

    kb_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_kb.id", ondelete="CASCADE"), nullable=False, comment="所属知识库 ID"
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, comment="版本号（如 0.1.0）")
    checksum: Mapped[str | None] = mapped_column(String(64), comment="该版本内容 SHA-256")
    readme_zh: Mapped[str | None] = mapped_column(Text, comment="中文说明存档")
    readme_en: Mapped[str | None] = mapped_column(Text, comment="英文说明存档")
    report_zh: Mapped[str | None] = mapped_column(Text, comment="中文审核报告存档")
    report_en: Mapped[str | None] = mapped_column(Text, comment="英文审核报告存档")
    audit_snapshot: Mapped[dict | None] = mapped_column(JSONB, comment="该版本审计快照")
    generated_by: Mapped[str | None] = mapped_column(
        String(16), comment="产物来源（template/model/external）"
    )

    __table_args__ = (
        UniqueConstraint("kb_id", "version", name="uq_pmcp_kb_version_kb_ver"),
        CheckConstraint("version <> ''", name="ck_pmcp_kb_version_nonempty"),
        {"comment": "知识库版本化双语存档（V3.0 M6 骨架，同 Skill 版本表惯例）"},
    )


class PmcpKbShare(BaseModel):
    """分享与审核关联：review_status + 合并目标 + 审核意见（审核流三期挂接 review 服务）。"""

    __tablename__ = "pmcp_kb_share"

    kb_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_kb.id", ondelete="CASCADE"), nullable=False, comment="发起分享的知识库 ID"
    )
    shared_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_user.id", ondelete="SET NULL"), comment="发起分享的用户 ID"
    )
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="分享审核状态（review 服务把守）"
    )
    merge_target_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_kb.id", ondelete="SET NULL"), comment="合并目标知识库 ID"
    )
    review_comment: Mapped[str | None] = mapped_column(Text, comment="审核意见（拒绝原因/迭代说明）")

    __table_args__ = (
        CheckConstraint("review_status <> ''", name="ck_pmcp_kb_share_status_nonempty"),
        {"comment": "知识库分享与审核关联（V3.0 M6 骨架，审核流复用 platform_mcp/review/）"},
    )
