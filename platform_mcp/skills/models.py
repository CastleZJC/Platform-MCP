"""Skill 生态 ORM 模型 — 版本化存档 / 广场公共池 / 黑名单（V3.0 M2，架构 §19.5.3 / §19.5.8）

- PmcpSkillVersion：每次新增/更新生成双语 README + 双语审核报告 + 审计快照，按 (skill_id, version)
  唯一存档，版本不可篡改（F-28）。
- PmcpSkillPlaza：广场公共池，独立于个人库 pmcp_skill —— "广场副本不受未审核更新影响"天然成立；
  embedding 列（BGE-M3 语义搜索，JSONB 规范存储 + 内存余弦降级）由 migration 007 追加（§19.5.6）；
  pgvector 原生列 embedding_vec 仅生产可装扩展时由 migration 007 条件创建，ORM 不声明（仅原生 SQL 读写，
  避免 pgvector python 包硬依赖）。
- PmcpSkillBlacklist：用户屏蔽广场/个人 Skill，Web+MCP 双端不可见仅黑名单页可见，可撤销（F-34）。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpSkillVersion(BaseModel):
    __tablename__ = "pmcp_skill_version"

    skill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_skill.id", ondelete="CASCADE"), nullable=False, comment="所属 Skill ID"
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, comment="版本号（如 0.1.0）")
    checksum: Mapped[str | None] = mapped_column(String(64), comment="该版本源码包 SHA-256")
    readme_zh: Mapped[str | None] = mapped_column(Text, comment="中文 README（存档不可篡改）")
    readme_en: Mapped[str | None] = mapped_column(Text, comment="英文 README")
    report_zh: Mapped[str | None] = mapped_column(Text, comment="中文审核报告（合规规则命中 + 广场比对结论）")
    report_en: Mapped[str | None] = mapped_column(Text, comment="英文审核报告")
    audit_snapshot: Mapped[dict | None] = mapped_column(JSONB, comment="该版本审计快照（规则命中摘要）")
    generated_by: Mapped[str | None] = mapped_column(String(16), comment="产物来源(template/model，架构 §19.5.6)")
    # migration 014：多语言补足产物（{locale: text}；tier template < model < external，本地永不覆盖 external）
    readme_extra: Mapped[dict | None] = mapped_column(JSONB, comment="多语言 README 补足（{locale: text}）")
    report_extra: Mapped[dict | None] = mapped_column(JSONB, comment="多语言审核报告补足（{locale: text}）")

    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_pmcp_skill_version_skill_ver"),
        CheckConstraint("version <> ''", name="ck_pmcp_skill_version_nonempty"),
        {"comment": "Skill 版本化双语存档（README/审核报告/审计快照，V3.0 M2）"},
    )


class PmcpSkillPlaza(BaseModel):
    __tablename__ = "pmcp_skill_plaza"

    skill_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="广场 Skill 编码")
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="广场 Skill 名称")
    description: Mapped[str | None] = mapped_column(Text, comment="Skill 描述")
    version: Mapped[str | None] = mapped_column(String(32), comment="当前发布版本（独立 version 链）")
    uploader_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_user.id", ondelete="SET NULL"), comment="分享者用户 ID"
    )
    involve_flags: Mapped[list | None] = mapped_column(JSONB, comment="涉库/涉服务器标记（audit R2/R3 派生，M3）")
    iteration_note: Mapped[str | None] = mapped_column(Text, comment="admin 合并迭代说明")
    source_path: Mapped[str | None] = mapped_column(Text, comment="广场副本包存储路径")
    source_checksum: Mapped[str | None] = mapped_column(String(64), comment="广场副本包 SHA-256")
    status: Mapped[str] = mapped_column(
        String(16), server_default="PUBLISHED", nullable=False, comment="广场状态(PUBLISHED/DISABLED)"
    )
    # migration 007：BGE-M3 语义向量（JSONB 规范存储 + 内存余弦降级，架构 §19.5.6 / VNF-02）。
    # pgvector 原生列 embedding_vec 不在此声明（仅 EmbeddingStore 原生 SQL 读写，避免 pgvector 包硬依赖）。
    embedding: Mapped[list | None] = mapped_column(JSONB, comment="Skill 语义向量（BGE-M3 / 降级哈希，JSONB 存储）")

    __table_args__ = ({"comment": "Skill 广场公共池（独立于个人库，V3.0）"},)


class PmcpPlazaVersion(BaseModel):
    """广场 Skill 版本归档（文件级版本管理仅限广场；approve/merge 快照，手工回退脚本消费）。"""

    __tablename__ = "pmcp_plaza_version"

    plaza_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_skill_plaza.id", ondelete="CASCADE"), nullable=False, comment="广场 Skill ID"
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, comment="版本号（如 0.1.0）")
    snapshot_path: Mapped[str | None] = mapped_column(
        Text, comment="版本快照目录（{upload_dir}/_plaza_versions/{plaza_id}/{version}）"
    )
    file_manifest: Mapped[list | None] = mapped_column(JSONB, comment="文件清单 [{path,size,sha256}]")
    checksum: Mapped[str | None] = mapped_column(String(64), comment="该版本源码包 SHA-256")
    source_version: Mapped[str | None] = mapped_column(
        String(64), comment="提交人版本（来源版本，不透传为广场版本）"
    )
    audit_snapshot: Mapped[dict | None] = mapped_column(JSONB, comment="该版本审计快照")

    __table_args__ = (
        UniqueConstraint("plaza_id", "version", name="uq_pmcp_plaza_version_plaza_ver"),
        {"comment": "Skill 广场版本归档（仅广场 Skill 版本管理；个人/系统 Skill 仅最新版）"},
    )


class PmcpSkillBlacklist(BaseModel):
    __tablename__ = "pmcp_skill_blacklist"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_user.id", ondelete="CASCADE"), nullable=False, comment="屏蔽发起用户 ID"
    )
    target_plaza_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_skill_plaza.id", ondelete="CASCADE"), comment="屏蔽的广场 Skill ID"
    )
    target_skill_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_skill.id", ondelete="CASCADE"), comment="屏蔽的个人 Skill ID"
    )
    reason: Mapped[str | None] = mapped_column(String(512), comment="屏蔽原因（可选）")

    __table_args__ = (
        UniqueConstraint("user_id", "target_plaza_id", name="uq_pmcp_skill_blacklist_plaza"),
        UniqueConstraint("user_id", "target_skill_id", name="uq_pmcp_skill_blacklist_skill"),
        CheckConstraint(
            "target_plaza_id IS NOT NULL OR target_skill_id IS NOT NULL",
            name="ck_pmcp_skill_blacklist_has_target",
        ),
        {"comment": "Skill 黑名单（用户屏蔽，双端不可见仅黑名单页可见，V3.0 M2）"},
    )


class PmcpPlazaMerge(BaseModel):
    """广场 merge 工作台（slim，migration 014）——build 临时包 + 冲突清单 admin 裁决 + publish/discard。"""

    __tablename__ = "pmcp_plaza_merge"

    merge_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="合并工作台令牌（build 返回，get_skill_file/publish 引用）"
    )
    plaza_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_skill_plaza.id", ondelete="CASCADE"), nullable=False, comment="目标广场 Skill ID"
    )
    source_skills: Mapped[list] = mapped_column(
        JSONB, nullable=False, comment="来源个人 Skill [{skill_id, role: primary|secondary}]"
    )
    base_version: Mapped[str | None] = mapped_column(
        String(64), comment="3-way 基线版本（copied_from_plaza_version 或 admin 指定）"
    )
    new_version: Mapped[str | None] = mapped_column(String(64), comment="目标发布版本")
    conflicts: Mapped[list | None] = mapped_column(
        JSONB, comment="冲突清单 [{path, candidates, resolution}]"
    )
    audit_summary: Mapped[dict | None] = mapped_column(JSONB, comment="14 条审计预跑摘要（build 时）")
    snapshot_path: Mapped[str | None] = mapped_column(
        String(512), comment="临时合并包目录（{upload_dir}/_plaza_merge/{plaza_id}/{token}）"
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default="BUILT", nullable=False, comment="状态(BUILT/PUBLISHED/DISCARDED)"
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, comment="创建 admin 用户名")

    __table_args__ = ({"comment": "广场 merge 工作台（文件级并集 + admin 裁决，2026-09-10）"},)
