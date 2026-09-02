"""分组管理 ORM 模型 — V3.0 统一组（组员+数据源+服务器多对多）

对应 migration 005：取代 V2.1 的两类分离组（pmcp_datasource_group / pmcp_server_group /
两张 group_member / pmcp_user_group）。
"""

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpGroup(BaseModel):
    __tablename__ = "pmcp_group"

    group_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="组名称")
    description: Mapped[str | None] = mapped_column(String(512), comment="组描述")
    env_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="环境标识(DEV/UAT/PROD)")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-停用")

    __table_args__ = ({"comment": "统一组（组员+数据源+服务器多对多，V3.0）"},)


class PmcpGroupUser(BaseModel):
    __tablename__ = "pmcp_group_user"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_group.id"), nullable=False, comment="组ID")
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_user.id"), nullable=False, comment="用户ID")

    __table_args__ = ({"comment": "统一组组员（用户）关联"},)


class PmcpGroupDatasource(BaseModel):
    __tablename__ = "pmcp_group_datasource"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_group.id"), nullable=False, comment="组ID")
    datasource_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_datasource.id"), nullable=False, comment="数据源ID"
    )

    __table_args__ = ({"comment": "统一组成员（数据源）关联"},)


class PmcpGroupServer(BaseModel):
    __tablename__ = "pmcp_group_server"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_group.id"), nullable=False, comment="组ID")
    server_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_server.id"), nullable=False, comment="服务器ID")

    __table_args__ = ({"comment": "统一组成员（服务器）关联"},)
