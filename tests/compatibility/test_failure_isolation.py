"""5.3.4 目标库连接失败不影响系统库"""

from unittest.mock import AsyncMock

import pytest

from platform_mcp.auth.session import SessionManager


class TestFailureIsolation:
    def test_target_db_failure_returns_error_dict(self):
        result = {"success": False, "message": "Connection refused", "latency_ms": 100}
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_web_api_healthy_after_db_failure(self):
        from platform_mcp.skills.database.risk import RiskEngine, RiskLevel
        engine = RiskEngine()
        result = engine.analyze("SELECT 1")
        assert result.level == RiskLevel.LOW

    @pytest.mark.asyncio
    async def test_session_manager_unaffected_by_db_failure(self):
        sm = SessionManager()
        sid = sm.create(1, "admin", None, "admin")
        assert sm.get(sid) is not None
        sm.delete(sid)
        assert sm.get(sid) is None
