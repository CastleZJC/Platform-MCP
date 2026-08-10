"""5.2.5 PROD 数据源权限隔离验证"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.datasource.manager import DatasourceManager, ConnectionParams


class TestProdIsolation:
    @pytest.mark.asyncio
    async def test_resolve_prod_datasource_returns_prod_params(self):
        """resolve_connection_params() 不做权限检查，仅返回连接参数。
        MCP 层 PROD 隔离由 _check_env_permission() 实现，
        已在 test_async_execution.py::TestMcpEnvPermission 中覆盖。
        """
        manager = DatasourceManager()
        mock_ds = MagicMock()
        mock_ds.db_type = "oracle"
        mock_ds.host = "prod-db"
        mock_ds.port = 1521
        mock_ds.username = "readonly"
        mock_ds.encrypted_password = "AES:test"
        mock_ds.instance_name = "PROD"
        mock_ds.service_name = None
        mock_ds.database = None
        mock_ds.query_timeout = 300
        mock_ds.max_concurrent = 5
        mock_ds.env_code = "PROD"
        mock_ds.datasource_code = "prod_oracle"

        with patch.object(manager, "get_datasource", return_value=mock_ds), \
             patch("platform_mcp.datasource.manager._get_crypto_utils") as mock_crypto:
            mock_crypto_obj = MagicMock()
            mock_crypto_obj.decrypt.return_value = "password"
            mock_crypto.return_value = mock_crypto_obj
            params = await manager.resolve_connection_params("prod_oracle")
        assert params.env_code == "PROD"

    @pytest.mark.asyncio
    async def test_dev_datasource_accessible(self):
        manager = DatasourceManager()
        mock_ds = MagicMock()
        mock_ds.db_type = "mysql"
        mock_ds.host = "dev-db"
        mock_ds.port = 3306
        mock_ds.username = "dev"
        mock_ds.encrypted_password = None
        mock_ds.instance_name = None
        mock_ds.service_name = None
        mock_ds.database = None
        mock_ds.query_timeout = 300
        mock_ds.max_concurrent = 5
        mock_ds.env_code = "DEV"
        mock_ds.datasource_code = "dev_mysql"

        with patch.object(manager, "get_datasource", return_value=mock_ds):
            params = await manager.resolve_connection_params("dev_mysql")
        assert params.env_code == "DEV"
        assert params.db_type == "mysql"
