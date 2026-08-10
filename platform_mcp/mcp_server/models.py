"""Skill 注册 ORM 模型"""

from sqlalchemy import SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpSkill(BaseModel):
    __tablename__ = "pmcp_skill"

    skill_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="Skill 编码")
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="Skill 名称")
    description: Mapped[str | None] = mapped_column(Text, comment="Skill 描述")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="状态 1-启用 0-禁用")
    register_method: Mapped[str | None] = mapped_column(String(32), comment="注册方式(decorator/form/upload)")
    tool_count: Mapped[int] = mapped_column(SmallInteger, server_default="0", comment="Tool 数量")

    __table_args__ = ({"comment": "Skill 注册信息"},)
