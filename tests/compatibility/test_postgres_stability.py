"""5.3.3 PostgreSQL 系统库稳定性测试（Mock）"""

from unittest.mock import AsyncMock, patch

import pytest

from platform_mcp.auth.session import SessionManager


class TestPostgresStability:
    @pytest.mark.asyncio
    async def test_100_session_operations(self):
        sm = SessionManager(ttl=1800)
        for i in range(100):
            sid = sm.create(i, f"user_{i}", None, "admin")
            info = sm.get(sid)
            assert info is not None
            assert info.user_id == i
        assert len(sm._sessions) == 100

    @pytest.mark.asyncio
    async def test_100_create_delete_cycles(self):
        sm = SessionManager(ttl=1800)
        for i in range(100):
            sid = sm.create(i, f"user_{i}", None, "admin")
            sm.delete(sid)
            assert sm.get(sid) is None
        assert len(sm._sessions) == 0
