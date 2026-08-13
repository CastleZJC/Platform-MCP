"""分组管理 ORM 模型 — 数据源组、服务器组、用户-组关联"""

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpDatasourceGroup(BaseModel):
    __tablename__ = "pmcp_datasource_group"

    group_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="组名称")
    description: Mapped[str | None] = mapped_column(String(512), comment="组描述")
    env_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="环境标识(DEV/UAT/PROD)")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")

    __table_args__ = ({"comment": "数据源组"},)


class PmcpServerGroup(BaseModel):
    __tablename__ = "pmcp_server_group"

    group_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="组名称")
    description: Mapped[str | None] = mapped_column(String(512), comment="组描述")
    env_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="环境标识(DEV/UAT/PROD)")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")

    __table_args__ = ({"comment": "服务器组"},)


class PmcpDatasourceGroupMember(BaseModel):
    __tablename__ = "pmcp_datasource_group_member"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_datasource_group.id"), nullable=False, comment="数据源组ID")
    datasource_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_datasource.id"), nullable=False, comment="数据源ID")

    __table_args__ = ({"comment": "数据源组成员"},)


class PmcpServerGroupMember(BaseModel):
    __tablename__ = "pmcp_server_group_member"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_server_group.id"), nullable=False, comment="服务器组ID")
    server_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_server.id"), nullable=False, comment="服务器ID")

    __table_args__ = ({"comment": "服务器组成员"},)


class PmcpUserGroup(BaseModel):
    __tablename__ = "pmcp_user_group"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_user.id"), nullable=False, comment="用户ID")
    group_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="组类型(datasource/server)")
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="组ID(datasource_group.id/server_group.id)")

    __table_args__ = ({"comment": "用户-组关联"},)