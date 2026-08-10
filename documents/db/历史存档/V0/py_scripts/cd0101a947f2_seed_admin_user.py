"""seed admin user and roles

Revision ID: cd0101a947f2
Revises: cc0101a947f1
Create Date: 2026-06-16

Seeds pmcp_role (admin/developer) + pmcp_user (admin / admin123 via bcrypt)
+ pmcp_user_role (admin -> admin). ON CONFLICT / NOT EXISTS 保证幂等。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "cd0101a947f2"
down_revision: Union[str, None] = "cc0101a947f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ADMIN_PWD_HASH = "$2b$12$BbcnlpLG9XY1tSJoTX75IOl6mFz1PWKven0kAE8ufaOZCs/gcD6XS"


def upgrade() -> None:
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
    op.execute(
        "DELETE FROM pmcp_user_role WHERE user_id IN ("
        "  SELECT id FROM pmcp_user WHERE username = 'admin'"
        ")"
    )
    op.execute("DELETE FROM pmcp_user WHERE username = 'admin'")
    op.execute("DELETE FROM pmcp_role WHERE role_code IN ('admin', 'developer')")
