"""系统参数配置 ORM 模型"""

from sqlalchemy import SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpSystemConfig(BaseModel):
    __tablename__ = "pmcp_system_config"

    config_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="配置键")
    config_value: Mapped[str | None] = mapped_column(Text, comment="配置值")
    config_type: Mapped[str | None] = mapped_column(String(32), comment="值类型(string/int/json/bool)")
    description: Mapped[str | None] = mapped_column(String(512), comment="配置说明")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")

    __table_args__ = ({"comment": "系统参数配置"},)
