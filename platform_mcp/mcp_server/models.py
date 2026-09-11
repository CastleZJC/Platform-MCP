"""Skill 注册 ORM 模型"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpSkill(BaseModel):
    __tablename__ = "pmcp_skill"

    skill_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="Skill 编码")
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="Skill 名称")
    description: Mapped[str | None] = mapped_column(Text, comment="Skill 描述")
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="ENABLED",
        comment="Skill 状态(ENABLED/PENDING_REVIEW/REJECTED/DISABLED，V3.0 M2 扩展 8 状态)",
    )
    register_method: Mapped[str | None] = mapped_column(String(32), comment="注册方式(decorator/form/upload)")
    tool_count: Mapped[int] = mapped_column(SmallInteger, server_default="0", comment="Tool 数量")
    # 二期新增字段：Skill 源码上传与合规审计
    source_path: Mapped[str | None] = mapped_column(Text, comment="解压后包存储路径")
    source_checksum: Mapped[str | None] = mapped_column(String(64), comment="上传包 SHA-256")
    source_format: Mapped[str | None] = mapped_column(String(10), comment="包格式(7z/zip)")
    version: Mapped[str | None] = mapped_column(String(32), comment="Skill 版本")
    audit_status: Mapped[str | None] = mapped_column(String(16), comment="审计状态(pending/passed/failed/warning)")
    audit_result: Mapped[dict | None] = mapped_column(JSONB, comment="审计摘要（规则命中数、严重级别分布）")
    readme_generated: Mapped[bool | None] = mapped_column(Boolean, comment="是否自动生成了 README.md")
    # V3.0 M2（migration 006）：广场分享与生命周期
    plaza_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pmcp_skill_plaza.id", ondelete="SET NULL"), comment="关联广场副本 ID"
    )
    origin: Mapped[str] = mapped_column(
        String(16), server_default="ORIGINAL", nullable=False, comment="来源(ORIGINAL 原创/PLAZA 广场复制)"
    )
    share_status: Mapped[str] = mapped_column(
        String(16), server_default="unshared", nullable=False, comment="分享状态(unshared 未分享/shared 已入广场)"
    )
    review_comment: Mapped[str | None] = mapped_column(
        Text, comment="最近一次审核意见(admin approve/merge/reject 决策，owner 可见，M5 邮件 {{reason}} 源)"
    )
    # migration 014：复制来源广场版本（add-to-my 记录；老版本合并的 3-way base）
    copied_from_plaza_version: Mapped[str | None] = mapped_column(
        String(64), comment="复制来源广场版本（add-to-my 记录，3-way merge base）"
    )

    __table_args__ = ({"comment": "Skill 注册信息"},)
