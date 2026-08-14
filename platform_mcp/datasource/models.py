"""数据源 ORM 模型"""

from sqlalchemy import CheckConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpDatasource(BaseModel):
    __tablename__ = "pmcp_datasource"

    datasource_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="数据源编码")
    datasource_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="数据源名称")
    db_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="数据库类型(oracle/mysql)")
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    instance_name: Mapped[str | None] = mapped_column(String(128), comment="实例名/SID")
    service_name: Mapped[str | None] = mapped_column(String(128), comment="Oracle 服务名")
    database: Mapped[str | None] = mapped_column(String(128), comment="MySQL 默认数据库")
    username: Mapped[str] = mapped_column(String(128), nullable=False, comment="连接用户名")
    encrypted_password: Mapped[str | None] = mapped_column(String(512), comment="AES密文密码")
    env_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="环境标识(DEV/UAT/PROD)")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", comment="1-启用 0-禁用")
    max_concurrent: Mapped[int] = mapped_column(SmallInteger, server_default="5", comment="最大并发数")
    query_timeout: Mapped[int] = mapped_column(SmallInteger, server_default="300", comment="查询超时(秒)")
    remark: Mapped[str | None] = mapped_column(String(512), comment="备注")

    __table_args__ = (
        CheckConstraint("datasource_code <> ''", name="ck_pmcp_datasource_datasource_code_nonempty"),
        {"comment": "数据源配置"},
    )

