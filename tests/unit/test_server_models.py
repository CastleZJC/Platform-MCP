"""skills.server 模型单元测试 — 验证 ORM 表结构注册"""

from platform_mcp.common.database import Base
from platform_mcp.server.models import PmcpServer, PmcpServerPermission


class TestServerModels:
    def test_pmcp_server_table_registered(self):
        assert "pmcp_server" in Base.metadata.tables

    def test_pmcp_server_permission_table_registered(self):
        assert "pmcp_server_permission" in Base.metadata.tables

    def test_pmcp_server_columns(self):
        cols = {c.name for c in PmcpServer.__table__.columns}
        expected = {
            "id", "server_code", "server_name", "host", "ssh_port", "username",
            "encrypted_password", "encrypted_ssh_key", "env_code", "status",
            "max_concurrent", "command_timeout", "allowed_paths", "forbidden_paths",
            "remark", "inserted_at", "updated_at", "inserted_by", "updated_by",
        }
        assert expected.issubset(cols), f"missing: {expected - cols}"

    def test_pmcp_server_permission_columns(self):
        cols = {c.name for c in PmcpServerPermission.__table__.columns}
        expected = {"id", "server_id", "user_id", "role_id", "permission_type"}
        assert expected.issubset(cols), f"missing: {expected - cols}"

    def test_server_code_unique(self):
        col = PmcpServer.__table__.columns["server_code"]
        assert col.unique is True

    def test_server_code_nullable_false(self):
        col = PmcpServer.__table__.columns["server_code"]
        assert col.nullable is False

    def test_ssh_port_default_22(self):
        col = PmcpServer.__table__.columns["ssh_port"]
        sd = str(col.server_default.arg)
        assert "22" in sd

    def test_status_default_1(self):
        col = PmcpServer.__table__.columns["status"]
        sd = str(col.server_default.arg)
        assert "1" in sd

    def test_max_concurrent_default_3(self):
        col = PmcpServer.__table__.columns["max_concurrent"]
        sd = str(col.server_default.arg)
        assert "3" in sd

    def test_tablename(self):
        assert PmcpServer.__tablename__ == "pmcp_server"
        assert PmcpServerPermission.__tablename__ == "pmcp_server_permission"
