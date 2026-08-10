"""fix indexes and constraints naming

Revision ID: cb0101a947ee
Revises: ba0102b846dd
Create Date: 2026-06-12 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "cb0101a947ee"
down_revision = "ba0102b846dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename unique constraints to standard naming convention
    op.execute(
        "ALTER TABLE pmcp_datasource "
        "RENAME CONSTRAINT pmcp_datasource_datasource_code_key "
        "TO un_pmcp_datasource_datasource_code"
    )
    op.execute(
        "ALTER TABLE pmcp_user "
        "RENAME CONSTRAINT pmcp_user_username_key "
        "TO un_pmcp_user_username"
    )
    op.execute(
        "ALTER TABLE pmcp_role "
        "RENAME CONSTRAINT pmcp_role_role_code_key "
        "TO un_pmcp_role_role_code"
    )
    op.execute(
        "ALTER TABLE pmcp_permission "
        "RENAME CONSTRAINT pmcp_permission_permission_code_key "
        "TO un_pmcp_permission_permission_code"
    )
    op.execute(
        "ALTER TABLE pmcp_skill "
        "RENAME CONSTRAINT pmcp_skill_skill_code_key "
        "TO un_pmcp_skill_skill_code"
    )
    op.execute(
        "ALTER TABLE pmcp_system_config "
        "RENAME CONSTRAINT pmcp_system_config_config_key_key "
        "TO un_pmcp_system_config_config_key"
    )

    # 2. Add audit_log indexes
    op.execute(
        "CREATE INDEX idx_pmcp_audit_log_inserted_at ON pmcp_audit_log USING brin (inserted_at)"
    )
    op.create_index("idx_pmcp_audit_log_operator", "pmcp_audit_log", ["operator"])
    op.create_index("idx_pmcp_audit_log_result_status", "pmcp_audit_log", ["result_status"])
    op.create_index("idx_pmcp_audit_log_trace_id", "pmcp_audit_log", ["trace_id"])

    # 3. Add FK column indexes
    op.create_index("idx_pmcp_user_role_user_id", "pmcp_user_role", ["user_id"])
    op.create_index("idx_pmcp_user_role_role_id", "pmcp_user_role", ["role_id"])
    op.create_index("idx_pmcp_role_permission_role_id", "pmcp_role_permission", ["role_id"])
    op.create_index(
        "idx_pmcp_role_permission_permission_id", "pmcp_role_permission", ["permission_id"]
    )
    op.create_index(
        "idx_pmcp_datasource_permission_datasource_id",
        "pmcp_datasource_permission",
        ["datasource_id"],
    )
    op.create_index(
        "idx_pmcp_datasource_permission_user_id", "pmcp_datasource_permission", ["user_id"]
    )
    op.create_index(
        "idx_pmcp_datasource_permission_role_id", "pmcp_datasource_permission", ["role_id"]
    )


def downgrade() -> None:
    # 3. Drop FK column indexes
    op.drop_index("idx_pmcp_datasource_permission_role_id", "pmcp_datasource_permission")
    op.drop_index("idx_pmcp_datasource_permission_user_id", "pmcp_datasource_permission")
    op.drop_index("idx_pmcp_datasource_permission_datasource_id", "pmcp_datasource_permission")
    op.drop_index("idx_pmcp_role_permission_permission_id", "pmcp_role_permission")
    op.drop_index("idx_pmcp_role_permission_role_id", "pmcp_role_permission")
    op.drop_index("idx_pmcp_user_role_role_id", "pmcp_user_role")
    op.drop_index("idx_pmcp_user_role_user_id", "pmcp_user_role")

    # 2. Drop audit_log indexes
    op.drop_index("idx_pmcp_audit_log_trace_id", "pmcp_audit_log")
    op.drop_index("idx_pmcp_audit_log_result_status", "pmcp_audit_log")
    op.drop_index("idx_pmcp_audit_log_operator", "pmcp_audit_log")
    op.execute("DROP INDEX idx_pmcp_audit_log_inserted_at")

    # 1. Revert constraint names
    op.execute(
        "ALTER TABLE pmcp_system_config "
        "RENAME CONSTRAINT un_pmcp_system_config_config_key "
        "TO pmcp_system_config_config_key_key"
    )
    op.execute(
        "ALTER TABLE pmcp_skill "
        "RENAME CONSTRAINT un_pmcp_skill_skill_code "
        "TO pmcp_skill_skill_code_key"
    )
    op.execute(
        "ALTER TABLE pmcp_permission "
        "RENAME CONSTRAINT un_pmcp_permission_permission_code "
        "TO pmcp_permission_permission_code_key"
    )
    op.execute(
        "ALTER TABLE pmcp_role "
        "RENAME CONSTRAINT un_pmcp_role_role_code "
        "TO pmcp_role_role_code_key"
    )
    op.execute(
        "ALTER TABLE pmcp_user "
        "RENAME CONSTRAINT un_pmcp_user_username "
        "TO pmcp_user_username_key"
    )
    op.execute(
        "ALTER TABLE pmcp_datasource "
        "RENAME CONSTRAINT un_pmcp_datasource_datasource_code "
        "TO pmcp_datasource_datasource_code_key"
    )
