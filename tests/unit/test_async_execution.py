"""异步执行 + MCP 环境权限校验 测试"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.skills.database import DatabaseSkill, _check_env_permission, _cleanup_expired_executions, _execution_store


@pytest.fixture(autouse=True)
def _clear_store():
    _execution_store.clear()
    yield
    _execution_store.clear()


# --- 异步执行 ---


class TestAsyncExecution:
    @pytest.mark.asyncio
    async def test_async_exec_returns_execution_id(self):
        skill = DatabaseSkill()
        with (
            patch("platform_mcp.skills.database.risk_engine") as mock_risk,
            patch("platform_mcp.datasource.manager.datasource_manager") as mock_ds,
            patch("platform_mcp.skills.database._check_env_permission"),
        ):
            mock_risk.analyze.return_value = MagicMock(needs_confirm=False, level=MagicMock(value="LOW"))
            mock_ds.resolve_connection_params = AsyncMock(return_value=MagicMock())

            with patch("platform_mcp.skills.database.executor.sql_executor") as mock_exec:
                mock_exec.execute_query.return_value = MagicMock(
                    success=True, rows=[], columns=[], row_count=0, affected_rows=0, duration_ms=10, error_message=None, truncated=False, risk_level="LOW"
                )

                result = await skill._execute_sql_text(
                    {"sql_text": "SELECT 1", "datasource_code": "ds1", "async_exec": True}, None
                )

        assert result["success"] is True
        assert "execution_id" in result
        assert result["status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_sync_exec_no_execution_id(self):
        skill = DatabaseSkill()
        with (
            patch("platform_mcp.skills.database.risk_engine") as mock_risk,
            patch("platform_mcp.datasource.manager.datasource_manager") as mock_ds,
            patch("platform_mcp.skills.database._check_env_permission"),
        ):
            mock_risk.analyze.return_value = MagicMock(needs_confirm=False, level=MagicMock(value="LOW"))
            mock_ds.resolve_connection_params = AsyncMock(return_value=MagicMock())

            with patch("platform_mcp.skills.database.executor.sql_executor") as mock_exec:
                from platform_mcp.skills.database.executor import ExecutionResult

                mock_exec.execute_query = AsyncMock(return_value=ExecutionResult(success=True))

                result = await skill._execute_sql_text(
                    {"sql_text": "SELECT 1", "datasource_code": "ds1"}, None
                )

        assert "execution_id" not in result
        assert result["success"] is True

    def test_get_execution_status_after_store(self):
        skill = DatabaseSkill()
        eid = "test-exec-1"
        _execution_store[eid] = {
            "status": "SUCCESS",
            "result": {"success": True},
            "risk_level": "LOW",
            "_created_at": time.monotonic(),
        }

        result = skill._get_execution_status({"execution_id": eid})
        assert result["success"] is True
        assert result["status"] == "SUCCESS"

    def test_execution_status_expired(self):
        skill = DatabaseSkill()
        eid = "expired-exec"
        _execution_store[eid] = {
            "status": "PENDING",
            "_created_at": time.monotonic() - 2000,  # > _EXECUTION_TTL
        }

        result = skill._get_execution_status({"execution_id": eid})
        assert result["success"] is False
        assert "不存在" in result["message"]


# --- MCP 环境权限校验 ---


class TestMcpEnvPermission:
    def test_admin_can_access_prod(self):
        with patch("platform_mcp.config.get_settings") as mock_settings:
            mock_settings.return_value.mcp.operator_role = "admin"
            mock_settings.return_value.mcp.allowed_envs = None
            _check_env_permission("PROD")

    def test_developer_cannot_access_prod(self):
        from platform_mcp.common.exceptions import SkillError

        with patch("platform_mcp.config.get_settings") as mock_settings:
            mock_settings.return_value.mcp.operator_role = "developer"
            mock_settings.return_value.mcp.allowed_envs = None
            with pytest.raises(SkillError, match="PROD"):
                _check_env_permission("PROD")

    def test_developer_can_access_dev(self):
        with patch("platform_mcp.config.get_settings") as mock_settings:
            mock_settings.return_value.mcp.operator_role = "developer"
            mock_settings.return_value.mcp.allowed_envs = None
            _check_env_permission("DEV")

    def test_allowed_envs_restricts_access(self):
        from platform_mcp.common.exceptions import SkillError

        with patch("platform_mcp.config.get_settings") as mock_settings:
            mock_settings.return_value.mcp.operator_role = "admin"
            mock_settings.return_value.mcp.allowed_envs = ["DEV", "TEST"]
            with pytest.raises(SkillError, match="PROD"):
                _check_env_permission("PROD")

    def test_allowed_envs_none_allows_all(self):
        with patch("platform_mcp.config.get_settings") as mock_settings:
            mock_settings.return_value.mcp.operator_role = "admin"
            mock_settings.return_value.mcp.allowed_envs = None
            _check_env_permission("PROD")
            _check_env_permission("DEV")


class TestAsyncExecutionFullFlow:
    """P2-4: 异步执行轮询完整流程测试"""

    def test_polling_state_transitions_pending_running_success(self):
        """完整轮询：PENDING → RUNNING → SUCCESS"""
        skill = DatabaseSkill()
        eid = "flow-exec-1"

        # 1. 初始 PENDING
        _execution_store[eid] = {
            "status": "PENDING",
            "result": None,
            "risk_level": "LOW",
            "_created_at": time.monotonic(),
        }
        r1 = skill._get_execution_status({"execution_id": eid})
        assert r1["success"] is True
        assert r1["status"] == "PENDING"

        # 2. 任务开始 RUNNING
        _execution_store[eid]["status"] = "RUNNING"
        r2 = skill._get_execution_status({"execution_id": eid})
        assert r2["success"] is True
        assert r2["status"] == "RUNNING"

        # 3. 完成 SUCCESS
        _execution_store[eid]["status"] = "SUCCESS"
        _execution_store[eid]["result"] = {"success": True, "row_count": 5}
        r3 = skill._get_execution_status({"execution_id": eid})
        assert r3["success"] is True
        assert r3["status"] == "SUCCESS"
        assert r3["result"]["row_count"] == 5

    def test_polling_state_failed(self):
        """失败状态：FAILED"""
        skill = DatabaseSkill()
        eid = "failed-exec"
        _execution_store[eid] = {
            "status": "FAILED",
            "result": {"success": False, "error_message": "syntax error"},
            "_created_at": time.monotonic(),
        }
        r = skill._get_execution_status({"execution_id": eid})
        assert r["success"] is True  # 查询本身成功
        assert r["status"] == "FAILED"
        assert r["result"]["error_message"] == "syntax error"

    def test_polling_state_error(self):
        """异常状态：ERROR（执行过程抛异常）"""
        skill = DatabaseSkill()
        eid = "error-exec"
        _execution_store[eid] = {
            "status": "ERROR",
            "result": {"success": False, "error_message": "connection lost"},
            "_created_at": time.monotonic(),
        }
        r = skill._get_execution_status({"execution_id": eid})
        assert r["status"] == "ERROR"

    def test_polling_nonexistent_execution(self):
        """查询不存在的 execution_id 返回失败"""
        skill = DatabaseSkill()
        r = skill._get_execution_status({"execution_id": "nonexistent-xyz"})
        assert r["success"] is False
        assert "不存在" in r["message"]

    @pytest.mark.asyncio
    async def test_full_async_flow_completes_to_success(self):
        """端到端：async_exec=true 提交 → 后台任务执行 → 最终 SUCCESS"""
        skill = DatabaseSkill()
        with (
            patch("platform_mcp.skills.database.risk_engine") as mock_risk,
            patch("platform_mcp.datasource.manager.datasource_manager") as mock_ds,
            patch("platform_mcp.skills.database._check_env_permission"),
        ):
            mock_risk.analyze.return_value = MagicMock(needs_confirm=False, level=MagicMock(value="LOW"))
            mock_ds.resolve_connection_params = AsyncMock(return_value=MagicMock())

            with patch("platform_mcp.skills.database.executor.sql_executor") as mock_exec:
                from platform_mcp.skills.database.executor import ExecutionResult

                mock_exec.execute_query = AsyncMock(return_value=ExecutionResult(
                    success=True, rows=[], columns=[], row_count=1, affected_rows=0,
                    duration_ms=5, error_message=None, truncated=False, risk_level="LOW",
                ))

                # 提交异步任务
                result = await skill._execute_sql_text(
                    {"sql_text": "SELECT 1", "datasource_code": "ds1", "async_exec": True}, None
                )

        assert result["success"] is True
        assert "execution_id" in result
        eid = result["execution_id"]

        # 等待后台任务完成（多次轮询，最多等 1 秒）
        import asyncio
        final_status = None
        for _ in range(20):
            await asyncio.sleep(0.05)
            status = skill._get_execution_status({"execution_id": eid})
            if status["status"] in ("SUCCESS", "FAILED", "ERROR"):
                final_status = status
                break

        assert final_status is not None, "后台任务未在预期时间内完成"
        assert final_status["status"] == "SUCCESS"

    def test_cleanup_expired_executions(self):
        """过期 execution 自动清理"""
        _execution_store["expired-1"] = {
            "status": "PENDING",
            "_created_at": time.monotonic() - 10000,  # 远超 TTL
        }
        _execution_store["active-1"] = {
            "status": "PENDING",
            "_created_at": time.monotonic(),  # 未过期
        }
        _cleanup_expired_executions()
        assert "expired-1" not in _execution_store
        assert "active-1" in _execution_store
