"""005_unified_group_roles_locale_skill_status — V3.0 M0 统一组模型 + 三角色 + locale + Skill 状态机列

Revision ID: 005
Revises: 004
Create Date: 2026-09-02

变更内容（技术架构说明文档 §19.5.4/§19.5.8）：
1. 统一组模型：pmcp_group + pmcp_group_user / pmcp_group_datasource / pmcp_group_server 三张成员表
   （UNIQUE(env_code, group_name)；成员表 UNIQUE(group_id, 资源id)）
2. 存量回填：数据源组与服务器组按"同 env 同名合并"迁入统一组（回填校验 SQL 见本文件尾部注释）
3. DROP 5 张旧组表（pmcp_datasource_group / pmcp_server_group / 2 张 group_member / pmcp_user_group）
4. pmcp_user 新增 locale 列（界面语言，V3.0 i18n）
5. pmcp_role seed 第三角色 user（一般用户）
6. pmcp_skill.status 由 SMALLINT 转 VARCHAR(16) 状态机：
   1→ENABLED / 2→PENDING_REVIEW / 3→REJECTED / 其他→DISABLED
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_GROUP_TABLES = (
    "pmcp_datasource_group_member",
    "pmcp_server_group_member",
    "pmcp_user_group",
    "pmcp_datasource_group",
    "pmcp_server_group",
)


def _create_unified_tables() -> None:
    op.create_table(
        "pmcp_group",
        sa.Column("group_name", sa.String(length=128), nullable=False, comment="组名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="组描述"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-停用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("env_code", "group_name", name="uq_pmcp_group_env_name"),
        comment="统一组（组员+数据源+服务器多对多，V3.0）",
    )
    for name, fk_col, fk_table, res_comment in (
        ("pmcp_group_user", "user_id", "pmcp_user", "组员（用户）"),
        ("pmcp_group_datasource", "datasource_id", "pmcp_datasource", "组成员（数据源）"),
        ("pmcp_group_server", "server_id", "pmcp_server", "组成员（服务器）"),
    ):
        op.create_table(
            name,
            sa.Column("group_id", sa.BigInteger(), nullable=False, comment="组ID"),
            sa.Column(fk_col, sa.BigInteger(), nullable=False, comment=f"{res_comment}ID"),
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("inserted_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["group_id"], ["pmcp_group.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint([fk_col], [f"{fk_table}.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("group_id", fk_col, name=f"uq_{name}_pair"),
            comment=f"统一组{res_comment}关联",
        )
        op.create_index(f"idx_{name}_group_id", name, ["group_id"])
        op.create_index(f"idx_{name}_{fk_col}", name, [fk_col])


def _backfill_unified_groups() -> None:
    # 数据源组先入统一组
    op.execute(
        "INSERT INTO pmcp_group (group_name, description, env_code, status, inserted_by, inserted_at, updated_at) "
        "SELECT g.group_name, g.description, g.env_code, g.status, g.inserted_by, now(), now() "
        "FROM pmcp_datasource_group g "
        "ON CONFLICT (env_code, group_name) DO NOTHING"
    )
    op.execute(
        "INSERT INTO pmcp_group_datasource (group_id, datasource_id, inserted_by) "
        "SELECT ng.id, m.datasource_id, ng.inserted_by "
        "FROM pmcp_datasource_group g "
        "JOIN pmcp_group ng ON ng.group_name = g.group_name AND ng.env_code = g.env_code "
        "JOIN pmcp_datasource_group_member m ON m.group_id = g.id "
        "ON CONFLICT (group_id, datasource_id) DO NOTHING"
    )
    # 服务器组按"同 env 同名合并"：已存在则复用，否则新建
    op.execute(
        "INSERT INTO pmcp_group (group_name, description, env_code, status, inserted_by, inserted_at, updated_at) "
        "SELECT s.group_name, s.description, s.env_code, s.status, s.inserted_by, now(), now() "
        "FROM pmcp_server_group s "
        "ON CONFLICT (env_code, group_name) DO NOTHING"
    )
    op.execute(
        "INSERT INTO pmcp_group_server (group_id, server_id, inserted_by) "
        "SELECT ng.id, m.server_id, ng.inserted_by "
        "FROM pmcp_server_group s "
        "JOIN pmcp_group ng ON ng.group_name = s.group_name AND ng.env_code = s.env_code "
        "JOIN pmcp_server_group_member m ON m.group_id = s.id "
        "ON CONFLICT (group_id, server_id) DO NOTHING"
    )
    # 用户-组关联（两类合并去重）
    op.execute(
        "INSERT INTO pmcp_group_user (user_id, group_id, inserted_by) "
        "SELECT ug.user_id, ng.id, ug.inserted_by FROM pmcp_user_group ug "
        "JOIN pmcp_datasource_group dg ON ug.group_type = 'datasource' AND ug.group_id = dg.id "
        "JOIN pmcp_group ng ON ng.group_name = dg.group_name AND ng.env_code = dg.env_code "
        "ON CONFLICT (group_id, user_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO pmcp_group_user (user_id, group_id, inserted_by) "
        "SELECT ug.user_id, ng.id, ug.inserted_by FROM pmcp_user_group ug "
        "JOIN pmcp_server_group sg ON ug.group_type = 'server' AND ug.group_id = sg.id "
        "JOIN pmcp_group ng ON ng.group_name = sg.group_name AND ng.env_code = sg.env_code "
        "ON CONFLICT (group_id, user_id) DO NOTHING"
    )


def _drop_old_group_tables() -> None:
    for table in _OLD_GROUP_TABLES:
        op.drop_table(table)


def upgrade() -> None:
    _create_unified_tables()
    _backfill_unified_groups()
    _drop_old_group_tables()

    # pmcp_user.locale（界面语言，默认中文由应用层回退，不设库默认以便区分"未选择"）
    op.add_column(
        "pmcp_user",
        sa.Column("locale", sa.String(length=8), nullable=True, comment="界面语言(zh-CN/en-US，空=跟随系统默认)"),
    )

    # pmcp_role seed 第三角色：一般用户
    op.execute(
        "INSERT INTO pmcp_role (role_name, role_code, status, remark) VALUES "
        "('一般用户', 'user', 1, 'V3.0：无 database/server 权限，有 Skill 创建分享与广场权限') "
        "ON CONFLICT (role_code) DO NOTHING"
    )

    # pmcp_skill.status SMALLINT → VARCHAR(16) 状态机（M2 扩展为 8 状态）
    op.execute(
        "ALTER TABLE pmcp_skill ALTER COLUMN status DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE pmcp_skill ALTER COLUMN status TYPE VARCHAR(16) "
        "USING CASE status WHEN 1 THEN 'ENABLED' WHEN 2 THEN 'PENDING_REVIEW' "
        "WHEN 3 THEN 'REJECTED' ELSE 'DISABLED' END"
    )
    op.execute("COMMENT ON COLUMN pmcp_skill.status IS 'Skill 状态(ENABLED/PENDING_REVIEW/REJECTED/DISABLED，V3.0 M2 扩展 8 状态)'")
    op.execute("ALTER TABLE pmcp_skill ALTER COLUMN status SET DEFAULT 'ENABLED'")


def downgrade() -> None:
    # 逆转 Skill 状态
    op.execute("ALTER TABLE pmcp_skill ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE pmcp_skill ALTER COLUMN status TYPE SMALLINT "
        "USING CASE status WHEN 'ENABLED' THEN 1 WHEN 'PENDING_REVIEW' THEN 2 "
        "WHEN 'REJECTED' THEN 3 ELSE 0 END"
    )
    op.execute("COMMENT ON COLUMN pmcp_skill.status IS '状态 1-启用 0-禁用 2-待审核 3-已驳回'")
    op.execute("ALTER TABLE pmcp_skill ALTER COLUMN status SET DEFAULT '1'")

    # 删除第三角色
    op.execute("DELETE FROM pmcp_role WHERE role_code = 'user'")
    op.drop_column("pmcp_user", "locale")

    # 重建旧两类组表并把统一组数据按成员类型拆回（同组含两类成员时组行复制为两份）
    op.create_table(
        "pmcp_datasource_group",
        sa.Column("group_name", sa.String(length=128), nullable=False, comment="组名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="组描述"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="数据源组",
    )
    op.create_table(
        "pmcp_server_group",
        sa.Column("group_name", sa.String(length=128), nullable=False, comment="组名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="组描述"),
        sa.Column("env_code", sa.String(length=32), nullable=False, comment="环境标识(DEV/UAT/PROD)"),
        sa.Column("status", sa.SmallInteger(), server_default="1", nullable=False, comment="1-启用 0-禁用"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="服务器组",
    )
    for name, fk_col, fk_table in (
        ("pmcp_datasource_group_member", "datasource_id", "pmcp_datasource_group"),
        ("pmcp_server_group_member", "server_id", "pmcp_server_group"),
    ):
        op.create_table(
            name,
            sa.Column("group_id", sa.BigInteger(), nullable=False, comment="组ID"),
            sa.Column(fk_col, sa.BigInteger(), nullable=False, comment="资源ID"),
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("inserted_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["group_id"], [f"{fk_table}.id"]),
            sa.ForeignKeyConstraint([fk_col], [f"pmcp_{'datasource' if fk_col == 'datasource_id' else 'server'}.id"]),
            comment=name,
        )
    op.create_table(
        "pmcp_user_group",
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("group_type", sa.String(length=32), nullable=False, comment="组类型(datasource/server)"),
        sa.Column("group_id", sa.BigInteger(), nullable=False, comment="组ID"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("inserted_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["pmcp_user.id"]),
        comment="用户-组关联",
    )
    op.execute(
        "INSERT INTO pmcp_datasource_group (group_name, description, env_code, status, inserted_by, inserted_at, updated_at) "
        "SELECT DISTINCT g.group_name, g.description, g.env_code, g.status, g.inserted_by, now(), now() "
        "FROM pmcp_group g WHERE EXISTS (SELECT 1 FROM pmcp_group_datasource m WHERE m.group_id = g.id)"
    )
    op.execute(
        "INSERT INTO pmcp_server_group (group_name, description, env_code, status, inserted_by, inserted_at, updated_at) "
        "SELECT DISTINCT g.group_name, g.description, g.env_code, g.status, g.inserted_by, now(), now() "
        "FROM pmcp_group g WHERE EXISTS (SELECT 1 FROM pmcp_group_server m WHERE m.group_id = g.id)"
    )
    op.execute(
        "INSERT INTO pmcp_datasource_group_member (group_id, datasource_id, inserted_by) "
        "SELECT dg.id, m.datasource_id, m.inserted_by FROM pmcp_group_datasource m "
        "JOIN pmcp_group ng ON ng.id = m.group_id "
        "JOIN pmcp_datasource_group dg ON dg.group_name = ng.group_name AND dg.env_code = ng.env_code"
    )
    op.execute(
        "INSERT INTO pmcp_server_group_member (group_id, server_id, inserted_by) "
        "SELECT sg.id, m.server_id, m.inserted_by FROM pmcp_group_server m "
        "JOIN pmcp_group ng ON ng.id = m.group_id "
        "JOIN pmcp_server_group sg ON sg.group_name = ng.group_name AND sg.env_code = ng.env_code"
    )
    op.execute(
        "INSERT INTO pmcp_user_group (user_id, group_type, group_id, inserted_by) "
        "SELECT u.user_id, 'datasource', dg.id, u.inserted_by FROM pmcp_group_user u "
        "JOIN pmcp_group ng ON ng.id = u.group_id "
        "JOIN pmcp_datasource_group dg ON dg.group_name = ng.group_name AND dg.env_code = ng.env_code "
        "WHERE EXISTS (SELECT 1 FROM pmcp_datasource_group_member m WHERE m.group_id = dg.id)"
    )
    op.execute(
        "INSERT INTO pmcp_user_group (user_id, group_type, group_id, inserted_by) "
        "SELECT u.user_id, 'server', sg.id, u.inserted_by FROM pmcp_group_user u "
        "JOIN pmcp_group ng ON ng.id = u.group_id "
        "JOIN pmcp_server_group sg ON sg.group_name = ng.group_name AND sg.env_code = ng.env_code "
        "WHERE EXISTS (SELECT 1 FROM pmcp_server_group_member m WHERE m.group_id = sg.id)"
    )
    op.drop_table("pmcp_group_user")
    op.drop_table("pmcp_group_datasource")
    op.drop_table("pmcp_group_server")
    op.drop_table("pmcp_group")


# ==================== 回填校验 SQL（迁移后在目标库执行核对） ====================
# 1) 组数对账：统一组数应 = 旧两类组按 (env_code, group_name) 去重后的组数
#    SELECT COUNT(DISTINCT (env_code, group_name)) 期望值来自：
#      SELECT env_code, group_name FROM pmcp_datasource_group UNION SELECT env_code, group_name FROM pmcp_server_group
#    （在 DROP 前执行；DROP 后以统一组数对照迁移前记录）
# 2) 成员对账：
#    SELECT COUNT(*) FROM pmcp_group_datasource 应 = COUNT(*) FROM pmcp_datasource_group_member（DROP 前）
#    SELECT COUNT(*) FROM pmcp_group_server   应 = COUNT(*) FROM pmcp_server_group_member（DROP 前）
# 3) 用户关联对账：COUNT(DISTINCT (user_id, group_id)) FROM pmcp_user_group 应 = COUNT(*) FROM pmcp_group_user
