"""用户、角色 ORM 模型"""

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpUser(BaseModel):
    __tablename__ = "pmcp_user"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128), comment="邮箱地址")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")

    __table_args__ = ({"comment": "用户信息"},)


class PmcpRole(BaseModel):
    __tablename__ = "pmcp_role"

    role_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色名称")
    role_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="角色标识")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")
    remark: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = ({"comment": "角色信息"},)


class PmcpUserRole(BaseModel):
    __tablename__ = "pmcp_user_role"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_user.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_role.id"), nullable=False)

    __table_args__ = ({"comment": "用户角色关系"},)


