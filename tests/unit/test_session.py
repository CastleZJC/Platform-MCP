"""SessionManager 单元测试 — 创建/获取/删除/TTL"""

import time
from unittest.mock import patch

from platform_mcp.auth.session import SessionManager, SessionInfo


class TestSessionManager:
    def setup_method(self):
        self.manager = SessionManager(ttl=1800)

    def test_create_returns_session_id(self):
        sid = self.manager.create(1, "admin", "管理员", "admin")
        assert isinstance(sid, str)
        assert len(sid) > 10

    def test_get_valid_session_returns_info(self):
        sid = self.manager.create(1, "admin", "管理员", "admin")
        info = self.manager.get(sid)
        assert info is not None
        assert info.user_id == 1
        assert info.username == "admin"
        assert info.role_code == "admin"

    def test_get_nonexistent_returns_none(self):
        assert self.manager.get("nonexistent") is None

    def test_delete_removes_session(self):
        sid = self.manager.create(1, "admin", "管理员", "admin")
        self.manager.delete(sid)
        assert self.manager.get(sid) is None

    def test_delete_nonexistent_no_error(self):
        self.manager.delete("nonexistent")

    def test_expired_session_returns_none(self):
        sid = self.manager.create(1, "admin", "管理员", "admin")
        with patch("platform_mcp.auth.session.time.time", return_value=time.time() + 2000):
            assert self.manager.get(sid) is None

    def test_get_updates_last_access(self):
        sid = self.manager.create(1, "admin", "管理员", "admin")
        info1 = self.manager.get(sid)
        assert info1 is not None
        first_access = info1.last_access
        with patch("platform_mcp.auth.session.time.time", return_value=time.time() + 100):
            info2 = self.manager.get(sid)
        assert info2 is not None
        assert info2.last_access > first_access

    def test_cleanup_expired_sessions(self):
        sid1 = self.manager.create(1, "user1", None, "admin")
        now = time.time()
        # Manually age the session
        self.manager._sessions[sid1].last_access = now - 2000
        self.manager._cleanup()
        assert len(self.manager._sessions) == 0

    def test_multiple_sessions_independent(self):
        sid1 = self.manager.create(1, "admin", None, "admin")
        sid2 = self.manager.create(2, "dev", None, "developer")
        info1 = self.manager.get(sid1)
        info2 = self.manager.get(sid2)
        assert info1.username == "admin"
        assert info2.username == "dev"
        self.manager.delete(sid1)
        assert self.manager.get(sid2) is not None
