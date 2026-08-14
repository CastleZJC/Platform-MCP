"""服务器 ORM 模型 — 镜像 datasource/models.py 结构"""

from sqlalchemy import CheckConstraint, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpServer(BaseModel):
    __tablename__ = "pmcp_server"

    server_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="服务器编码")
    server_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="服务器名称")
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    ssh_port: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="22", comment="SSH 端口")
    username: Mapped[str] = mapped_column(String(128), nullable=False, comment="登录用户名")
    encrypted_password: Mapped[str | None] = mapped_column(String(512), comment="AES 密文密码（与 ssh_key 二选一）")
    encrypted_ssh_key: Mapped[str | None] = mapped_column(Text, comment="AES 密文 PEM 私钥（与 password 二选一）")
    env_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="环境标识(DEV/UAT/PROD)")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")
    max_concurrent: Mapped[int] = mapped_column(SmallInteger, server_default="3", comment="同服务器并发 SSH 上限")
    command_timeout: Mapped[int] = mapped_column(SmallInteger, server_default="1800", comment="命令超时(秒)")
    allowed_paths: Mapped[str | None] = mapped_column(Text, comment="JSON 数组：SFTP/upload/download 远端白名单")
    forbidden_paths: Mapped[str | None] = mapped_column(Text, comment="JSON 数组：远端黑名单（rm -rf 目标排除）")
    remark: Mapped[str | None] = mapped_column(String(512), comment="备注")

    __table_args__ = (
        CheckConstraint("server_code <> ''", name="ck_pmcp_server_server_code_nonempty"),
        {"comment": "服务器配置"},
    )


