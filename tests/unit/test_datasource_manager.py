"""DatasourceManager 单元测试 — 连接管理、健康检查"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.datasource.manager import ConnectionParams, DatasourceManager


def _mock_ds(code="ds1", db_type="oracle", host="10.0.0.1", port=1521,
             username="u", encrypted_password="AES:abc", env_code="DEV",
             instance_name=None, service_name=None, database=None, query_timeout=300,
             max_concurrent=5, status=1, datasource_name="测试"):
    ds = MagicMock()
    ds.datasource_code = code
    ds.datasource_name = datasource_name
    ds.db_type = db_type
    ds.host = host
    ds.port = port
    ds.username = username
    ds.encrypted_password = encrypted_password
    ds.instance_name = instance_name
    ds.service_name = service_name
    ds.database = database
    ds.query_timeout = query_timeout
    ds.max_concurrent = max_concurrent
    ds.env_code = env_code
    ds.status = status
    return ds


def _mock_session_context(result_scalar=None, result_scalars=None):
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = result_scalar
    mock_scalar_list = MagicMock()
    mock_scalar_list.all.return_value = result_scalars or []
    mock_result.scalars.return_value = mock_scalar_list
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# --- _get_crypto_utils ---

def test_get_crypto_utils_正常加载():
    with patch("platform_mcp.config.get_settings") as mock_gs, \
         patch("platform_mcp.common.crypto.CryptoUtils") as mock_crypto_cls, \
         patch("pathlib.Path") as mock_path_cls:
        mock_settings = MagicMock()
        mock_settings.datasource.crypto_key_path = "/path/to/key"
        mock_gs.return_value = mock_settings
        mock_path_cls.return_value.read_bytes.return_value = b"x" * 32
        import platform_mcp.datasource.manager as mod
        mod._get_crypto_utils()
        mock_crypto_cls.assert_called_once_with(b"x" * 32)


def test_get_crypto_utils_未配置key_path报ValueError():
    with patch("platform_mcp.config.get_settings") as mock_gs:
        mock_settings = MagicMock()
        mock_settings.datasource.crypto_key_path = None
        mock_gs.return_value = mock_settings
        import platform_mcp.datasource.manager as mod
        with pytest.raises(ValueError, match="crypto_key_path"):
            mod._get_crypto_utils()


# --- get_datasource ---

@pytest.mark.asyncio
async def test_get_datasource_找到返回():
    ds = _mock_ds()
    ctx, session = _mock_session_context(result_scalar=ds)
    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx):
        mgr = DatasourceManager()
        result = await mgr.get_datasource("ds1")
        assert result.datasource_code == "ds1"


@pytest.mark.asyncio
async def test_get_datasource_未找到报DataSourceError():
    from platform_mcp.common.exceptions import DataSourceError
    ctx, session = _mock_session_context(result_scalar=None)
    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx):
        mgr = DatasourceManager()
        with pytest.raises(DataSourceError, match="不存在或已禁用"):
            await mgr.get_datasource("nonexist")


# --- resolve_connection_params ---

@pytest.mark.asyncio
async def test_resolve_connection_params_解密密码():
    ds = _mock_ds(encrypted_password="AES:encrypted")
    ctx, _ = _mock_session_context(result_scalar=ds)
    mock_crypto = MagicMock()
    mock_crypto.decrypt.return_value = "plaintext_pwd"

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx), \
         patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=mock_crypto):
        mgr = DatasourceManager()
        params = await mgr.resolve_connection_params("ds1")
        assert params.password == "plaintext_pwd"
        assert params.db_type == "oracle"


# --- list_accessible_datasources ---

@pytest.mark.asyncio
async def test_list_accessible_有env过滤():
    ds = _mock_ds()
    ctx, session = _mock_session_context(result_scalars=[ds])
    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx):
        mgr = DatasourceManager()
        result = await mgr.list_accessible_datasources("DEV")
        assert len(result) == 1
        assert result[0]["datasource_code"] == "ds1"


@pytest.mark.asyncio
async def test_list_accessible_无env过滤():
    ds = _mock_ds()
    ctx, session = _mock_session_context(result_scalars=[ds])
    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx):
        mgr = DatasourceManager()
        result = await mgr.list_accessible_datasources()
        assert len(result) == 1


# --- test_connection ---

@pytest.mark.asyncio
async def test_test_connection_Oracle成功():
    ds = _mock_ds(db_type="oracle")
    ctx, _ = _mock_session_context(result_scalar=ds)
    mock_crypto = MagicMock()
    mock_crypto.decrypt.return_value = "pass"

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx), \
         patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=mock_crypto), \
         patch("platform_mcp.skills.database.connection.get_connection", return_value=conn_ctx), \
         patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.run_in_executor = AsyncMock(return_value=None)

        mgr = DatasourceManager()
        result = await mgr.test_connection("ds1")
        assert result["success"] is True
        assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_test_connection_MySQL成功():
    ds = _mock_ds(db_type="mysql", port=3306)
    ctx, _ = _mock_session_context(result_scalar=ds)
    mock_crypto = MagicMock()
    mock_crypto.decrypt.return_value = "pass"

    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(1,))
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx), \
         patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=mock_crypto), \
         patch("platform_mcp.skills.database.connection.get_connection", return_value=conn_ctx):
        mgr = DatasourceManager()
        result = await mgr.test_connection("ds1")
        assert result["success"] is True


@pytest.mark.asyncio
async def test_test_connection_失败返回错误信息():
    ds = _mock_ds(db_type="mysql")
    ctx, _ = _mock_session_context(result_scalar=ds)
    mock_crypto = MagicMock()
    mock_crypto.decrypt.return_value = "pass"

    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("platform_mcp.common.database._ensure_engine"), \
         patch("platform_mcp.common.database.async_session_factory", return_value=ctx), \
         patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=mock_crypto), \
         patch("platform_mcp.skills.database.connection.get_connection", return_value=conn_ctx):
        mgr = DatasourceManager()
        result = await mgr.test_connection("ds1")
        assert result["success"] is False
        assert "Connection refused" in result["message"]
