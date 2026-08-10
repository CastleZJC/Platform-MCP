"""Oracle 11g thick mode 兼容性测试（P1-5）

从 poc/oracle/v2_thick_sync_test.py 迁移关键断言到正式 pytest 套件。
使用 mock oracledb 避免依赖真实 Instant Client，CI 友好。

POC 原文件保留（CLAUDE.md dev 原则 10：脚本只能新增）。
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_oracledb():
    """Mock oracledb 模块，避免依赖真实 Instant Client"""
    mock = MagicMock()
    mock.init_oracle_client = MagicMock()
    # 模拟 thick mode 必需的属性
    mock.connect = MagicMock(return_value=MagicMock(close=MagicMock()))
    with patch.dict(sys.modules, {"oracledb": mock}):
        yield mock


class TestOracleThickModeInit:
    """Oracle thick mode 初始化测试"""

    def test_thick_mode_初始化_指定_lib_dir(self, mock_oracledb):
        """thick mode 必须传入 lib_dir（Oracle Instant Client 路径）"""
        with patch("platform_mcp.skills.database.connection._oracle_initialized", False), \
             patch("platform_mcp.config.get_settings") as mock_gs:
            mock_gs.return_value.datasource.oracle_instant_client_dir = "/opt/oracle/client"
            from platform_mcp.skills.database.connection import _ensure_oracle_client
            _ensure_oracle_client()
            mock_oracledb.init_oracle_client.assert_called_once_with(lib_dir="/opt/oracle/client")

    def test_thick_mode_未配置_lib_dir_抛_ValueError(self, mock_oracledb):
        """未配置 lib_dir 时抛 ValueError，提示需要 Oracle Instant Client"""
        with patch("platform_mcp.skills.database.connection._oracle_initialized", False), \
             patch("platform_mcp.config.get_settings") as mock_gs:
            mock_gs.return_value.datasource.oracle_instant_client_dir = ""
            from platform_mcp.skills.database.connection import _ensure_oracle_client
            with pytest.raises(ValueError, match="oracle_instant_client_dir"):
                _ensure_oracle_client()

    def test_thick_mode_初始化_幂等(self, mock_oracledb):
        """重复调用 _ensure_oracle_client 只初始化一次（_oracle_initialized flag）"""
        with patch("platform_mcp.skills.database.connection._oracle_initialized", True):
            from platform_mcp.skills.database.connection import _ensure_oracle_client
            _ensure_oracle_client()
            mock_oracledb.init_oracle_client.assert_not_called()


class TestOracleDSNConstruction:
    """Oracle DSN 构建测试（thick mode 必需）"""

    @pytest.mark.asyncio
    async def test_service_name_构建_斜杠分隔_DSN(self, mock_oracledb):
        """service_name 模式：host:port/service_name"""
        from platform_mcp.datasource.manager import ConnectionParams
        from platform_mcp.skills.database.connection import oracle_connection

        params = ConnectionParams(
            db_type="oracle", host="10.0.0.1", port=1521,
            username="user", password="pass",
            service_name="ORCL", instance_name=None, database=None,
        )
        with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
             patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=MagicMock(close=MagicMock()))
            mock_get_loop.return_value = mock_loop
            async with oracle_connection(params):
                pass

        # 验证 DSN 格式：service_name 用斜杠
        call_args = mock_loop.run_in_executor.call_args_list[0]
        connect_lambda = call_args[0][1]
        connect_lambda()
        mock_oracledb.connect.assert_called_with(
            user="user", password="pass", dsn="10.0.0.1:1521/ORCL"
        )

    @pytest.mark.asyncio
    async def test_instance_name_构建_冒号分隔_DSN(self, mock_oracledb):
        """instance_name (SID) 模式：host:port:instance_name"""
        from platform_mcp.datasource.manager import ConnectionParams
        from platform_mcp.skills.database.connection import oracle_connection

        params = ConnectionParams(
            db_type="oracle", host="10.0.0.1", port=1521,
            username="user", password="pass",
            service_name=None, instance_name="PROD", database=None,
        )
        with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
             patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=MagicMock(close=MagicMock()))
            mock_get_loop.return_value = mock_loop
            async with oracle_connection(params):
                pass

        call_args = mock_loop.run_in_executor.call_args_list[0]
        connect_lambda = call_args[0][1]
        connect_lambda()
        mock_oracledb.connect.assert_called_with(
            user="user", password="pass", dsn="10.0.0.1:1521:PROD"
        )

    @pytest.mark.asyncio
    async def test_默认_无_service_无_instance_仅_host_port(self, mock_oracledb):
        """无 service_name/instance_name 时：host:port"""
        from platform_mcp.datasource.manager import ConnectionParams
        from platform_mcp.skills.database.connection import oracle_connection

        params = ConnectionParams(
            db_type="oracle", host="10.0.0.1", port=1521,
            username="user", password="pass",
            service_name=None, instance_name=None, database=None,
        )
        with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
             patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=MagicMock(close=MagicMock()))
            mock_get_loop.return_value = mock_loop
            async with oracle_connection(params):
                pass

        call_args = mock_loop.run_in_executor.call_args_list[0]
        connect_lambda = call_args[0][1]
        connect_lambda()
        mock_oracledb.connect.assert_called_with(
            user="user", password="pass", dsn="10.0.0.1:1521"
        )


class TestOracleThickModeRequirement:
    """Oracle 11g thick mode 兼容性要求"""

    def test_thin_mode_不支持_oracle_11g(self, mock_oracledb):
        """oracledb thin mode 仅支持 Oracle 12.1+，11g 必须用 thick mode

        设计原则：connection.py 强制 _ensure_oracle_client 调用 init_oracle_client
        """
        with patch("platform_mcp.skills.database.connection._oracle_initialized", False), \
             patch("platform_mcp.config.get_settings") as mock_gs:
            mock_gs.return_value.datasource.oracle_instant_client_dir = "/opt/oracle/client"
            from platform_mcp.skills.database.connection import _ensure_oracle_client
            _ensure_oracle_client()
            # init_oracle_client 必须被调用（启用 thick mode）
            mock_oracledb.init_oracle_client.assert_called_once()
