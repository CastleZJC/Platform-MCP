import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 服务器侧 alembic.ini 硬编码开发库 URL，部署时通过 PLATFORM_DB_URL 覆盖
# 例：PLATFORM_DB_URL=postgresql://pmcp@127.0.0.1:5432/platform_mcp
_env_db_url = os.environ.get("PLATFORM_DB_URL")
if _env_db_url:
    config.set_main_option("sqlalchemy.url", _env_db_url)

# 导入所有 Model 以支持 autogenerate
from platform_mcp.common.database import Base  # noqa: E402
from platform_mcp.auth.models import (  # noqa: E402, F401
    PmcpUser, PmcpRole, PmcpUserRole,
)
from platform_mcp.datasource.models import PmcpDatasource  # noqa: E402, F401
from platform_mcp.server.models import PmcpServer  # noqa: E402, F401
from platform_mcp.audit.models import PmcpAuditLog, PmcpMcpCallLog, PmcpCryptoOperationLog  # noqa: E402, F401
from platform_mcp.mcp_server.models import PmcpSkill  # noqa: E402, F401
from platform_mcp.common.models import PmcpSystemConfig  # noqa: E402, F401
from platform_mcp.group.models import (  # noqa: E402, F401
    PmcpDatasourceGroup, PmcpServerGroup,
    PmcpDatasourceGroupMember, PmcpServerGroupMember,
    PmcpUserGroup,
)
from platform_mcp.skills.audit.models import PmcpSkillAuditReport  # noqa: E402, F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
