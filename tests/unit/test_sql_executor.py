"""5.1.2 SQLExecutor 单元测试 — 路径安全/格式化/Mock 连接"""

import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.skills.database.executor import SQLExecutor, ExecutionResult, _format_row


class TestFormatRow:
    def test_none_value(self):
        assert _format_row((None,)) == [None]

    def test_decimal_value(self):
        assert _format_row((Decimal("3.14"),)) == ["3.14"]

    def test_float_value(self):
        assert _format_row((1.5,)) == ["1.5"]

    def test_datetime_value(self):
        dt = datetime(2026, 6, 9, 12, 0, 0)
        assert _format_row((dt,)) == [dt.isoformat()]

    def test_bytes_value(self):
        assert _format_row((b"hello",)) == ["<BLOB 5B>"]

    def test_string_value(self):
        assert _format_row(("text",)) == ["text"]

    def test_int_value(self):
        assert _format_row((42,)) == ["42"]

    def test_mixed_types(self):
        row = (1, None, Decimal("2.5"), "hello", b"\x00\x01")
        result = _format_row(row)
        assert result == ["1", None, "2.5", "hello", "<BLOB 2B>"]


class TestValidateFilePath:
    def setup_method(self):
        self.executor = SQLExecutor()

    def test_non_sql_extension_raises(self):
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("test.txt")

    @patch("platform_mcp.skills.database.executor.Path")
    def test_symlink_raises(self, mock_path_cls):
        mock_path = MagicMock()
        mock_path.resolve.return_value = mock_path
        mock_path.suffix.lower.return_value = ".sql"
        mock_path.is_symlink.return_value = True
        mock_path_cls.return_value = mock_path
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("link.sql")

    @patch("platform_mcp.skills.database.executor.Path")
    def test_nonexistent_file_raises(self, mock_path_cls):
        mock_path = MagicMock()
        mock_path.resolve.return_value = mock_path
        mock_path.suffix.lower.return_value = ".sql"
        mock_path.is_symlink.return_value = False
        mock_path.exists.return_value = False
        mock_path_cls.return_value = mock_path
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("missing.sql")


class TestSQLExecutorMocked:
    def setup_method(self):
        self.executor = SQLExecutor()
        self.params = ConnectionParams(
            db_type="mysql", host="localhost", port=3306,
            username="root", password="", datasource_code="test",
        )

    @pytest.mark.asyncio
    async def test_execute_query_timeout(self):
        with patch.object(self.executor, "_do_execute", side_effect=asyncio.TimeoutError()):
            result = await self.executor.execute_query(self.params, "SELECT 1", timeout=1)
        assert result.success is False
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_query_exception(self):
        with patch.object(self.executor, "_do_execute", side_effect=Exception("conn failed")):
            result = await self.executor.execute_query(self.params, "SELECT 1")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_query_success(self):
        mock_result = ExecutionResult(success=True, columns=["id"], rows=[["1"]], row_count=1)
        with patch.object(self.executor, "_do_execute", return_value=mock_result):
            result = await self.executor.execute_query(self.params, "SELECT 1")
        assert result.success is True
        assert result.duration_ms >= 0

    def test_validate_file_path_超大文件_raises(self):
        mock_settings = MagicMock()
        mock_settings.datasource.allowed_sql_dirs = []
        mock_settings.datasource.max_file_size_mb = 1
        with patch("platform_mcp.config.get_settings", return_value=mock_settings), \
             patch("platform_mcp.skills.database.executor.Path") as mock_path_cls:
            mock_path = MagicMock()
            mock_path.resolve.return_value = mock_path
            mock_path.suffix = ".sql"
            mock_path.is_symlink.return_value = False
            mock_path.exists.return_value = True
            mock_path.stat.return_value.st_size = 2 * 1024 * 1024
            mock_path_cls.return_value = mock_path
            with pytest.raises(PathSecurityError, match="超过"):
                self.executor._validate_file_path("big.sql")

    def test_validate_file_path_不在白名单目录_raises(self):
        mock_settings = MagicMock()
        mock_settings.datasource.allowed_sql_dirs = ["/safe/dir"]
        mock_settings.datasource.max_file_size_mb = 10
        with patch("platform_mcp.config.get_settings", return_value=mock_settings), \
             patch("platform_mcp.skills.database.executor.Path") as mock_path_cls:
            evil_path = MagicMock()
            evil_path.resolve.return_value = evil_path
            evil_path.suffix = ".sql"
            evil_path.is_symlink.return_value = False
            evil_path.exists.return_value = True
            evil_path.stat.return_value.st_size = 100
            evil_path.__str__ = lambda s: "/evil/dir/bad.sql"

            safe_path = MagicMock()
            safe_path.resolve.return_value = safe_path
            safe_path.__str__ = lambda s: "/safe/dir"

            mock_path_cls.side_effect = lambda p: evil_path if "evil" in str(p) else safe_path
            with pytest.raises(PathSecurityError, match="白名单"):
                self.executor._validate_file_path("/evil/dir/bad.sql")

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_execute_oracle_有结果集(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.rowcount = 1
        mock_cursor.fetchmany.return_value = [(1, "test")]
        mock_cursor.close = MagicMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        async def run_sync(_executor, fn):
            return fn()
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = run_sync
            mock_get_loop.return_value = mock_loop

            oracle_params = ConnectionParams(
                db_type="oracle", host="10.0.0.1", port=1521,
                username="u", password="p", datasource_code="ds1",
            )
            result = await self.executor.execute_query(oracle_params, "SELECT id, name FROM t")
            assert result.success is True
            assert result.columns == ["id", "name"]
            mock_cursor.close.assert_called_once()

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_execute_oracle_无结果集(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.rowcount = 5
        mock_cursor.close = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        async def run_sync(_executor, fn):
            return fn()
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = run_sync
            mock_get_loop.return_value = mock_loop

            oracle_params = ConnectionParams(
                db_type="oracle", host="10.0.0.1", port=1521,
                username="u", password="p", datasource_code="ds1",
            )
            result = await self.executor.execute_query(oracle_params, "DELETE FROM t")
            assert result.success is True
            assert result.affected_rows == 5

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_execute_mysql_有结果集(self, mock_get_conn):
        mock_cursor = AsyncMock()
        mock_cursor.description = [("id",)]
        mock_cursor.rowcount = 1
        mock_cursor.fetchmany = AsyncMock(return_value=[(1,)])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = AsyncMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        mysql_params = ConnectionParams(
            db_type="mysql", host="localhost", port=3306,
            username="root", password="", datasource_code="ds1",
        )
        result = await self.executor.execute_query(mysql_params, "SELECT id FROM t")
        assert result.success is True
        assert result.columns == ["id"]

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_execute_mysql_无结果集(self, mock_get_conn):
        mock_cursor = AsyncMock()
        mock_cursor.description = None
        mock_cursor.rowcount = 3
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = AsyncMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        mysql_params = ConnectionParams(
            db_type="mysql", host="localhost", port=3306,
            username="root", password="", datasource_code="ds1",
        )
        result = await self.executor.execute_query(mysql_params, "UPDATE t SET x=1")
        assert result.success is True
        assert result.affected_rows == 3

    @patch.object(SQLExecutor, "execute_query")
    @patch.object(SQLExecutor, "_validate_file_path")
    @pytest.mark.asyncio
    async def test_execute_file_多语句顺序执行(self, mock_vfp, mock_eq):
        mock_path = MagicMock()
        mock_path.read_text.return_value = "SELECT 1; SELECT 2;"
        mock_vfp.return_value = mock_path

        r1 = ExecutionResult(success=True, columns=["1"], rows=[["1"]], row_count=1)
        r2 = ExecutionResult(success=True, columns=["2"], rows=[["2"]], row_count=1)
        mock_eq.side_effect = [r1, r2]

        results = await self.executor.execute_file("/test.sql", self.params)
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is True

    @patch.object(SQLExecutor, "execute_query")
    @patch.object(SQLExecutor, "_validate_file_path")
    @pytest.mark.asyncio
    async def test_execute_file_首条失败中断(self, mock_vfp, mock_eq):
        mock_path = MagicMock()
        mock_path.read_text.return_value = "BAD SQL; SELECT 2;"
        mock_vfp.return_value = mock_path

        r1 = ExecutionResult(success=False, error_message="syntax error")
        mock_eq.return_value = r1

        results = await self.executor.execute_file("/bad.sql", self.params)
        assert len(results) == 1
        assert results[0].success is False

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_execute_oracle_查询有结果集(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.rowcount = 1
        mock_cursor.fetchmany.return_value = [(1, "test")]
        mock_cursor.close = MagicMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        async def run_sync(_executor, fn):
            return fn()

        oracle_params = ConnectionParams(
            db_type="oracle", host="10.0.0.1", port=1521,
            username="u", password="p", datasource_code="ds1",
        )
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = run_sync
            mock_get_loop.return_value = mock_loop
            result = await self.executor.execute_query(oracle_params, "SELECT id, name FROM t")
            assert result.success is True
            assert result.columns == ["id", "name"]

    @patch("platform_mcp.skills.database.executor.get_connection")
    @pytest.mark.asyncio
    async def test_execute_oracle_异常回滚(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("oracle error")
        mock_cursor.close = MagicMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.rollback = MagicMock()

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_conn.return_value = conn_ctx

        async def run_sync(_executor, fn):
            return fn()

        oracle_params = ConnectionParams(
            db_type="oracle", host="10.0.0.1", port=1521,
            username="u", password="p", datasource_code="ds1",
        )
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = run_sync
            mock_get_loop.return_value = mock_loop
            result = await self.executor.execute_query(oracle_params, "BAD SQL")
            assert result.success is False
            mock_conn.rollback.assert_called_once()
            mock_cursor.close.assert_called_once()


class TestAllowedSqlDirsProdGuard:
    """allowed_sql_dirs 空值拦截 — BUG20260814163941 BUG-2：按目标资源 env_code 判定"""

    def setup_method(self):
        self.executor = SQLExecutor()

    def test_prod_target_empty_allowed_sql_dirs_raises(self, tmp_path):
        """PROD 目标数据源 + 未配置 allowed_sql_dirs 时抛 PathSecurityError"""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 1;")
        with patch("platform_mcp.config.get_settings") as mock_gs:
            mock_gs.return_value.datasource.allowed_sql_dirs = []
            mock_gs.return_value.datasource.max_file_size_mb = 10
            with pytest.raises(PathSecurityError, match="必须配置 allowed_sql_dirs"):
                self.executor._validate_file_path(str(sql_file), env_code="PROD")

    def test_dev_target_empty_allowed_sql_dirs_warns_but_allows(self, tmp_path):
        """DEV 目标数据源 + 未配置 allowed_sql_dirs 时仅告警，不抛错"""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 1;")
        with patch("platform_mcp.config.get_settings") as mock_gs:
            mock_gs.return_value.datasource.allowed_sql_dirs = []
            mock_gs.return_value.datasource.max_file_size_mb = 10
            path = self.executor._validate_file_path(str(sql_file), env_code="DEV")
            assert path.exists()

    def test_prod_deploy_dev_target_not_blocked(self, tmp_path):
        """BUG-2 核心场景：PROD 部署（settings.env=prod）操作 DEV 目标不应被误伤"""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 1;")
        with patch("platform_mcp.config.get_settings") as mock_gs:
            mock_gs.return_value.env = "prod"  # 部署环境为 prod，但目标数据源是 DEV
            mock_gs.return_value.datasource.allowed_sql_dirs = []
            mock_gs.return_value.datasource.max_file_size_mb = 10
            path = self.executor._validate_file_path(str(sql_file), env_code="DEV")
            assert path.exists()
