"""连接工厂单元测试 — oracle/mysql ephemeral 连接"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.datasource.manager import ConnectionParams


def _params(db_type="oracle", host="10.0.0.1", port=1521, username="user", password="pass",
            service_name=None, instance_name=None, database=None):
    return ConnectionParams(
        db_type=db_type, host=host, port=port, username=username, password=password,
        service_name=service_name, instance_name=instance_name, database=database,
    )


def _make_async_executor(sync_fn):
    """Wrap a sync function so run_in_executor calls it and returns a coroutine."""
    async def executor(_, fn):
        return fn()
    return executor


# --- _ensure_oracle_client ---

def test_ensure_oracle_client_未初始化时调用init():
    mock_oracle = MagicMock()
    with patch("platform_mcp.skills.database.connection._oracle_initialized", False), \
         patch("platform_mcp.config.get_settings") as mock_gs, \
         patch.dict(sys.modules, {"oracledb": mock_oracle}):
        mock_settings = MagicMock()
        mock_settings.datasource.oracle_instant_client_dir = "/opt/oracle/client"
        mock_gs.return_value = mock_settings
        from platform_mcp.skills.database.connection import _ensure_oracle_client
        _ensure_oracle_client()
        mock_oracle.init_oracle_client.assert_called_once_with(lib_dir="/opt/oracle/client")


def test_ensure_oracle_client_已初始化跳过():
    with patch("platform_mcp.skills.database.connection._oracle_initialized", True):
        from platform_mcp.skills.database.connection import _ensure_oracle_client
        _ensure_oracle_client()


def test_ensure_oracle_client_未配置lib_dir报ValueError():
    with patch("platform_mcp.skills.database.connection._oracle_initialized", False), \
         patch("platform_mcp.config.get_settings") as mock_gs:
        mock_settings = MagicMock()
        mock_settings.datasource.oracle_instant_client_dir = None
        mock_gs.return_value = mock_settings
        from platform_mcp.skills.database.connection import _ensure_oracle_client
        with pytest.raises(ValueError, match="oracle_instant_client_dir"):
            _ensure_oracle_client()


# --- oracle_connection ---

@pytest.mark.asyncio
async def test_oracle_connection_service_name构建DSN():
    params = _params(service_name="ORCL")
    mock_conn = MagicMock()
    mock_oracle = MagicMock()
    mock_oracle.connect.return_value = mock_conn

    with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
         patch.dict(sys.modules, {"oracledb": mock_oracle}), \
         patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.run_in_executor = AsyncMock(return_value=mock_conn)

        from platform_mcp.skills.database.connection import oracle_connection
        async with oracle_connection(params) as conn:
            assert conn is mock_conn

        call_args = mock_loop.run_in_executor.call_args_list[0]
        lambda_fn = call_args[0][1]
        result = lambda_fn()
        mock_oracle.connect.assert_called_once_with(
            user="user", password="pass", dsn="10.0.0.1:1521/ORCL"
        )


@pytest.mark.asyncio
async def test_oracle_connection_instance_name构建DSN():
    params = _params(instance_name="PROD")
    mock_conn = MagicMock()
    mock_oracle = MagicMock()
    mock_oracle.connect.return_value = mock_conn

    with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
         patch.dict(sys.modules, {"oracledb": mock_oracle}), \
         patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.run_in_executor = AsyncMock(return_value=mock_conn)

        from platform_mcp.skills.database.connection import oracle_connection
        async with oracle_connection(params) as conn:
            assert conn is mock_conn

        call_args = mock_loop.run_in_executor.call_args_list[0]
        call_args[0][1]()
        mock_oracle.connect.assert_called_once_with(
            user="user", password="pass", dsn="10.0.0.1:1521:PROD"
        )


@pytest.mark.asyncio
async def test_oracle_connection_默认DSN():
    params = _params()
    mock_conn = MagicMock()
    mock_oracle = MagicMock()
    mock_oracle.connect.return_value = mock_conn

    with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
         patch.dict(sys.modules, {"oracledb": mock_oracle}), \
         patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.run_in_executor = AsyncMock(return_value=mock_conn)

        from platform_mcp.skills.database.connection import oracle_connection
        async with oracle_connection(params) as conn:
            assert conn is mock_conn

        call_args = mock_loop.run_in_executor.call_args_list[0]
        call_args[0][1]()
        mock_oracle.connect.assert_called_once_with(
            user="user", password="pass", dsn="10.0.0.1:1521"
        )


@pytest.mark.asyncio
async def test_oracle_connection_异常时关闭连接():
    params = _params()
    mock_conn = MagicMock()
    mock_oracle = MagicMock()
    mock_oracle.connect.return_value = mock_conn

    with patch("platform_mcp.skills.database.connection._ensure_oracle_client"), \
         patch.dict(sys.modules, {"oracledb": mock_oracle}), \
         patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.run_in_executor = AsyncMock(return_value=mock_conn)

        from platform_mcp.skills.database.connection import oracle_connection
        async with oracle_connection(params) as conn:
            pass

        # Second run_in_executor call is the close in finally
        assert mock_loop.run_in_executor.call_count >= 2


# --- mysql_connection ---

@pytest.mark.asyncio
async def test_mysql_connection_成功():
    params = _params(db_type="mysql", port=3306, database="testdb")
    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.ensure_closed = AsyncMock()
    mock_aiomysql = MagicMock()
    mock_aiomysql.connect = AsyncMock(return_value=mock_conn)

    with patch.dict(sys.modules, {"aiomysql": mock_aiomysql}):
        from platform_mcp.skills.database.connection import mysql_connection
        async with mysql_connection(params) as conn:
            assert conn is mock_conn

        mock_aiomysql.connect.assert_called_once_with(
            host="10.0.0.1", port=3306, user="user", password="pass",
            db="testdb", charset="utf8mb4", connect_timeout=30,
        )


@pytest.mark.asyncio
async def test_mysql_connection_异常时关闭():
    params = _params(db_type="mysql", port=3306)
    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.ensure_closed = AsyncMock()
    mock_aiomysql = MagicMock()
    mock_aiomysql.connect = AsyncMock(return_value=mock_conn)

    with patch.dict(sys.modules, {"aiomysql": mock_aiomysql}):
        from platform_mcp.skills.database.connection import mysql_connection
        async with mysql_connection(params) as conn:
            pass

        mock_conn.close.assert_called_once()


# --- get_connection ---

@pytest.mark.asyncio
async def test_get_connection_oracle路由():
    params = _params(db_type="oracle")
    mock_conn = MagicMock()

    with patch("platform_mcp.skills.database.connection.oracle_connection") as mock_oc:
        mock_oc.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_oc.return_value.__aexit__ = AsyncMock(return_value=False)

        from platform_mcp.skills.database.connection import get_connection
        async with get_connection(params) as conn:
            assert conn is mock_conn
        mock_oc.assert_called_once_with(params)


@pytest.mark.asyncio
async def test_get_connection_mysql路由():
    params = _params(db_type="mysql")
    mock_conn = MagicMock()

    with patch("platform_mcp.skills.database.connection.mysql_connection") as mock_mc:
        mock_mc.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_mc.return_value.__aexit__ = AsyncMock(return_value=False)

        from platform_mcp.skills.database.connection import get_connection
        async with get_connection(params) as conn:
            assert conn is mock_conn
        mock_mc.assert_called_once_with(params)


@pytest.mark.asyncio
async def test_get_connection_不支持类型报ValueError():
    params = _params(db_type="postgres")

    from platform_mcp.skills.database.connection import get_connection
    with pytest.raises(ValueError, match="不支持的数据库类型"):
        async with get_connection(params):
            pass
