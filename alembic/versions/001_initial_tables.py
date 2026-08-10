"""001_initial_tables — 发布版初始 schema

Revision ID: 001
Revises:
Create Date: 2026-08-08 12:00:00

合并历史 10 个迭代（ba0102b846dd → ch0101a947f6）的最终态：
- 15 张系统表（pmcp_*）
- 完整索引与约束（统一命名 pk_/un_/idx_）
- 幂等 seed：admin / developer 角色 + admin 用户 + admin 角色

与 documents/db/20260808120000_initial_schema.sql（DDL 渲染）+ documents/db/20260808120001_seed_data.sql（DML）等价。
历史迭代归档于 documents/db/历史存档/V0/。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ADMIN_PWD_HASH = "$2b$12$BbcnlpLG9XY1tSJoTX75IOl6mFz1PWKven0kAE8ufaOZCs/gcD6XS"


def upgrade() -> None:
    # ==================== 实体表 ====================
    op.create_table(
        "pmcp_user",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password", sa.String(length=128), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=128), nullable=True, comment="邮箱地址"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="un_pmcp_user_username"),
        comment="用户信息",
    )

    op.create_table(
        "pmcp_role",
        sa.Column("role_name", sa.String(length=64), nullable=False, comment="角色名称"),
        sa.Column("role_code", sa.String(length=64), nullable=False, comment="角色标识"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_code", name="un_pmcp_role_role_code"),
        comment="角色信息",
    )

    op.create_table(
        "pmcp_permission",
        sa.Column("permission_name", sa.String(length=128), nullable=False, comment="权限名称"),
        sa.Column("permission_code", sa.String(length=128), nullable=False, comment="权限标识"),
        sa.Column("resource_type", sa.String(length=64), nullable=True, comment="资源类型(menu/button/api)"),
        sa.Column("resource_path", sa.String(length=256), nullable=True, comment="资源路径"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True, comment="父权限ID"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=True, comment="排序"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("permission_code", name="un_pmcp_permission_permission_code"),
        comment="权限定义",
    )

    op.create_table(
        "pmcp_skill",
        sa.Column("skill_code", sa.String(length=64), nullable=False, comment="Skill 编码"),
        sa.Column("skill_name", sa.String(length=128), nullable=False, comment="Skill 名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="Skill 描述"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="状态 1-启用 0-禁用"),
        sa.Column("register_method", sa.String(length=32), nullable=True, comment="注册方式(decorator/form/upload)"),
        sa.Column("tool_count", sa.SmallInteger(), server_default="0", nullable=False, comment="Tool 数量"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_code", name="un_pmcp_skill_skill_code"),
        comment="Skill 注册信息",
    )

    op.create_table(
        "pmcp_system_config",
        sa.Column("config_key", sa.String(length=128), nullable=False, comment="配置键"),
        sa.Column("config_value", sa.Text(), nullable=True, comment="配置值"),
        sa.Column("config_type", sa.String(length=32), nullable=True, comment="值类型(string/int/json/bool)"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="配置说明"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_key", name="un_pmcp_system_config_config_key"),
        comment="系统参数配置",
    )

    op.create_table(
        "pmcp_datasource",
        sa.Column("datasource_code", sa.String(length=64), nullable=False, comment="数据源编码"),
        sa.Column("datasource_name", sa.String(length=128), nullable=False, comment="数据源名称"),
        sa.Column("db_type", sa.String(length=32), nullable=False, comment="数据库类型(oracle/mysql)"),
        sa.Column("host", sa.String(length=256), nullable=False),
        sa.Column("port", sa.SmallInteger(), nullable=False),
        sa.Column("instance_name", sa.String(length=128), nullable=True, comment="实例名/SID"),
        sa.Column("username", sa.String(length=128), nullable=False, comment="连接用户名"),
        sa.Column("encrypted_password", sa.String(length=512), nullable=True, comment="AES密文密码"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/TEST/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("max_concurrent", sa.SmallInteger(), server_default="5", nullable=False, comment="最大并发数"),
        sa.Column("query_timeout", sa.SmallInteger(), server_default="300", nullable=False, comment="查询超时(秒)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True, comment="备注"),
        sa.Column("service_name", sa.String(length=128), nullable=True, comment="Oracle 服务名"),
        sa.Column("database", sa.String(length=128), nullable=True, comment="MySQL 默认数据库"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("datasource_code", name="un_pmcp_datasource_datasource_code"),
        comment="数据源配置",
    )

    op.create_table(
        "pmcp_server",
        sa.Column("server_code", sa.String(length=64), nullable=False, comment="服务器编码"),
        sa.Column("server_name", sa.String(length=128), nullable=False, comment="服务器名称"),
        sa.Column("host", sa.String(length=256), nullable=False),
        sa.Column("ssh_port", sa.SmallInteger(), nullable=False, server_default="22", comment="SSH 端口"),
        sa.Column("username", sa.String(length=128), nullable=False, comment="登录用户名"),
        sa.Column("encrypted_password", sa.String(length=512), nullable=True, comment="AES 密文密码（与 ssh_key 二选一）"),
        sa.Column("encrypted_ssh_key", sa.Text(), nullable=True, comment="AES 密文 PEM 私钥（与 password 二选一）"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("max_concurrent", sa.SmallInteger(), server_default="3", nullable=False, comment="同服务器并发 SSH 上限"),
        sa.Column("command_timeout", sa.SmallInteger(), server_default="300", nullable=False, comment="命令超时(秒)"),
        sa.Column("allowed_paths", sa.Text(), nullable=True, comment="JSON 数组：SFTP/upload/download 远端白名单"),
        sa.Column("forbidden_paths", sa.Text(), nullable=True, comment="JSON 数组：远端黑名单"),
        sa.Column("remark", sa.String(length=512), nullable=True, comment="备注"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_code"),
        comment="服务器配置",
    )
    op.create_index("idx_pmcp_server_env_code", "pmcp_server", ["env_code"])

    op.create_table(
        "pmcp_api_key",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="所属用户"),
        sa.Column("key_hash", sa.String(length=128), nullable=False, comment="SHA-256 哈希"),
        sa.Column("key_prefix", sa.String(length=16), nullable=False, comment="前8位用于识别"),
        sa.Column("description", sa.String(length=255), nullable=True, comment="备注"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1", comment="1=活跃 0=已撤销"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True, comment="最近使用时间"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="过期时间"),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("key_encrypted", sa.String(length=512), nullable=True, comment="AES 加密后的明文 Key，用于 admin reveal"),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pmcp_api_key_user_id", "pmcp_api_key", ["user_id"])
    op.create_unique_constraint("un_pmcp_api_key_key_hash", "pmcp_api_key", ["key_hash"])

    op.create_table(
        "pmcp_audit_log",
        sa.Column("trace_id", sa.String(length=64), nullable=True, comment="全链路追踪标识"),
        sa.Column("request_id", sa.String(length=64), nullable=True, comment="请求唯一标识"),
        sa.Column("operator", sa.String(length=64), nullable=True, comment="操作人"),
        sa.Column("skill_name", sa.String(length=64), nullable=True, comment="Skill 名称"),
        sa.Column("tool_name", sa.String(length=64), nullable=True, comment="Tool 名称"),
        sa.Column("resource_type", sa.String(length=64), nullable=True, comment="资源类型"),
        sa.Column("resource_id", sa.String(length=128), nullable=True, comment="资源标识"),
        sa.Column("env_code", sa.String(length=32), nullable=True, comment="环境标识"),
        sa.Column("request_summary", sa.Text(), nullable=True, comment="请求摘要"),
        sa.Column("result_status", sa.String(length=32), nullable=True, comment="结果状态(success/fail/error)"),
        sa.Column("risk_level", sa.String(length=16), nullable=True, comment="风险等级(LOW/MEDIUM/HIGH/CRITICAL)"),
        sa.Column("error_code", sa.String(length=32), nullable=True, comment="错误码"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True, comment="耗时毫秒"),
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="扩展数据(JSONB)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="审计日志",
    )
    op.execute("CREATE INDEX idx_pmcp_audit_log_inserted_at ON pmcp_audit_log USING brin (inserted_at)")
    op.create_index("idx_pmcp_audit_log_operator", "pmcp_audit_log", ["operator"])
    op.create_index("idx_pmcp_audit_log_result_status", "pmcp_audit_log", ["result_status"])
    op.create_index("idx_pmcp_audit_log_trace_id", "pmcp_audit_log", ["trace_id"])

    op.create_table(
        "pmcp_mcp_call_log",
        sa.Column("trace_id", sa.String(length=64), nullable=True, comment="全链路追踪标识"),
        sa.Column("tool_name", sa.String(length=64), nullable=True, comment="Tool 名称"),
        sa.Column("caller", sa.String(length=128), nullable=True, comment="调用方(Claude Code)"),
        sa.Column("datasource_code", sa.String(length=64), nullable=True, comment="数据源编码"),
        sa.Column("env_code", sa.String(length=32), nullable=True, comment="环境标识"),
        sa.Column("input_summary", sa.Text(), nullable=True, comment="输入摘要"),
        sa.Column("output_summary", sa.Text(), nullable=True, comment="输出摘要"),
        sa.Column("result_status", sa.String(length=32), nullable=True, comment="结果状态"),
        sa.Column("error_code", sa.String(length=32), nullable=True, comment="错误码"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True, comment="耗时毫秒"),
        sa.Column("confirm_token", sa.String(length=128), nullable=True, comment="确认令牌"),
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="扩展数据"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="MCP 调用日志",
    )

    op.create_table(
        "pmcp_crypto_operation_log",
        sa.Column("operator", sa.String(length=64), nullable=True, comment="操作人"),
        sa.Column("operation_type", sa.String(length=32), nullable=True, comment="操作类型(encrypt/decrypt)"),
        sa.Column("datasource_code", sa.String(length=64), nullable=True, comment="关联数据源编码"),
        sa.Column("algorithm", sa.String(length=32), nullable=True, comment="算法(AES-256-GCM/AES-256-CBC)"),
        sa.Column("result_status", sa.String(length=32), nullable=True, comment="结果状态"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="加解密操作日志",
    )

    # ==================== 关联表 ====================
    op.create_table(
        "pmcp_user_role",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="用户角色关系",
    )
    op.create_index("idx_pmcp_user_role_user_id", "pmcp_user_role", ["user_id"])
    op.create_index("idx_pmcp_user_role_role_id", "pmcp_user_role", ["role_id"])

    op.create_table(
        "pmcp_role_permission",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["permission_id"], ["pmcp_permission.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="角色权限关系",
    )
    op.create_index("idx_pmcp_role_permission_role_id", "pmcp_role_permission", ["role_id"])
    op.create_index("idx_pmcp_role_permission_permission_id", "pmcp_role_permission", ["permission_id"])

    op.create_table(
        "pmcp_datasource_permission",
        sa.Column("datasource_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="授权用户"),
        sa.Column("role_id", sa.BigInteger(), nullable=True, comment="授权角色"),
        sa.Column("permission_type", sa.String(length=32), nullable=False, comment="权限类型(query/manage)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["datasource_id"], ["pmcp_datasource.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="数据源权限关系",
    )
    op.create_index("idx_pmcp_datasource_permission_datasource_id", "pmcp_datasource_permission", ["datasource_id"])
    op.create_index("idx_pmcp_datasource_permission_user_id", "pmcp_datasource_permission", ["user_id"])
    op.create_index("idx_pmcp_datasource_permission_role_id", "pmcp_datasource_permission", ["role_id"])

    op.create_table(
        "pmcp_server_permission",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="授权用户"),
        sa.Column("role_id", sa.BigInteger(), nullable=True, comment="授权角色"),
        sa.Column("permission_type", sa.String(length=32), nullable=False, comment="权限类型(exec/upload/download/manage)"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["pmcp_server.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["pmcp_role.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="服务器权限关系",
    )
    op.create_index("idx_pmcp_server_permission_server_id", "pmcp_server_permission", ["server_id"])

    # ==================== 幂等 seed ====================
    op.execute(
        "INSERT INTO pmcp_role (role_name, role_code, status, remark) VALUES "
        "('系统管理员', 'admin', 1, NULL), "
        "('开发人员', 'developer', 1, NULL) "
        "ON CONFLICT (role_code) DO NOTHING"
    )
    op.execute(
        "INSERT INTO pmcp_user (username, password, nickname, email, status) VALUES "
        "('admin', '%s', '系统管理员', NULL, 1) "
        "ON CONFLICT (username) DO NOTHING" % _ADMIN_PWD_HASH
    )
    op.execute(
        "INSERT INTO pmcp_user_role (user_id, role_id) "
        "SELECT u.id, r.id FROM pmcp_user u, pmcp_role r "
        "WHERE u.username = 'admin' AND r.role_code = 'admin' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM pmcp_user_role ur WHERE ur.user_id = u.id AND ur.role_id = r.id"
        ")"
    )


def downgrade() -> None:
    op.drop_table("pmcp_server_permission")
    op.drop_index("idx_pmcp_server_env_code", table_name="pmcp_server")
    op.drop_table("pmcp_server")
    op.drop_table("pmcp_datasource_permission")
    op.drop_index("idx_pmcp_role_permission_permission_id", table_name="pmcp_role_permission")
    op.drop_index("idx_pmcp_role_permission_role_id", table_name="pmcp_role_permission")
    op.drop_table("pmcp_role_permission")
    op.drop_index("idx_pmcp_user_role_role_id", table_name="pmcp_user_role")
    op.drop_index("idx_pmcp_user_role_user_id", table_name="pmcp_user_role")
    op.drop_table("pmcp_user_role")
    op.drop_table("pmcp_crypto_operation_log")
    op.drop_table("pmcp_mcp_call_log")
    op.drop_index("idx_pmcp_audit_log_trace_id", table_name="pmcp_audit_log")
    op.drop_index("idx_pmcp_audit_log_result_status", table_name="pmcp_audit_log")
    op.drop_index("idx_pmcp_audit_log_operator", table_name="pmcp_audit_log")
    op.execute("DROP INDEX idx_pmcp_audit_log_inserted_at")
    op.drop_table("pmcp_audit_log")
    op.drop_index("idx_pmcp_api_key_user_id", table_name="pmcp_api_key")
    op.drop_table("pmcp_api_key")
    op.drop_index("idx_pmcp_datasource_permission_role_id", table_name="pmcp_datasource_permission")
    op.drop_index("idx_pmcp_datasource_permission_user_id", table_name="pmcp_datasource_permission")
    op.drop_index("idx_pmcp_datasource_permission_datasource_id", table_name="pmcp_datasource_permission")
    op.drop_table("pmcp_datasource")
    op.drop_table("pmcp_system_config")
    op.drop_table("pmcp_skill")
    op.drop_table("pmcp_permission")
    op.drop_table("pmcp_role")
    op.drop_table("pmcp_user")
