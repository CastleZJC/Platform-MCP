"""Skill 注册 ORM 模型"""

from sqlalchemy import BigInteger, Boolean, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpSkill(BaseModel):
    __tablename__ = "pmcp_skill"

    skill_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="Skill 编码")
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="Skill 名称")
    description: Mapped[str | None] = mapped_column(Text, comment="Skill 描述")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="状态 1-启用 0-禁用 2-待审核 3-已驳回")
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

    __table_args__ = ({"comment": "Skill 注册信息"},)
