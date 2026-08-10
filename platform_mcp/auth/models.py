"""用户、角色、权限 ORM 模型"""

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String, Text
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


class PmcpPermission(BaseModel):
    __tablename__ = "pmcp_permission"

    permission_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="权限名称")
    permission_code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="权限标识")
    resource_type: Mapped[str | None] = mapped_column(String(64), comment="资源类型(menu/button/api)")
    resource_path: Mapped[str | None] = mapped_column(String(256), comment="资源路径")
    parent_id: Mapped[int | None] = mapped_column(BigInteger, comment="父权限ID")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")
    sort_order: Mapped[int | None] = mapped_column(SmallInteger, server_default="0", comment="排序")

    __table_args__ = ({"comment": "权限定义"},)


class PmcpRolePermission(BaseModel):
    __tablename__ = "pmcp_role_permission"

    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_role.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_permission.id"), nullable=False)

    __table_args__ = ({"comment": "角色权限关系"},)
