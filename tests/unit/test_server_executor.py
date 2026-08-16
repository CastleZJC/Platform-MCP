"""skills.server.executor 单元测试 — mock asyncssh，验证路径校验与调用模式"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.server.manager import ServerConnParams
from platform_mcp.skills.server.executor import ServerExecutor, _MAX_FILE_SIZE_BYTES


def _make_params(allowed_paths=None, forbidden_paths=None) -> ServerConnParams:
    return ServerConnParams(
        server_code="APP-SAMPLE-1",
        host="127.0.0.1",
        ssh_port=22,
        username="user",
        password="pwd",
        env_code="DEV",
        max_concurrent=3,
        command_timeout=60,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
    )


class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_success_returns_exit_code(self):
        ex = ServerExecutor()
        params = _make_params()
        fake_result = MagicMock(exit_status=0, stdout="ok", stderr="")
        with patch("platform_mcp.skills.server.executor.ssh_connection") as mock_ssh:
            mock_conn = AsyncMock()
            mock_conn.run = AsyncMock(return_value=fake_result)
            mock_ssh.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ssh.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.execute_command(params, "uname -a")
        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == "ok"

    @pytest.mark.asyncio
    async def test_nonzero_exit_returns_failure(self):
        ex = ServerExecutor()
        params = _make_params()
        fake_result = MagicMock(exit_status=1, stdout="", stderr="boom")
        with patch("platform_mcp.skills.server.executor.ssh_connection") as mock_ssh:
            mock_conn = AsyncMock()
            mock_conn.run = AsyncMock(return_value=fake_result)
            mock_ssh.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ssh.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.execute_command(params, "false")
        assert result.success is False
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_exception_returns_error_message(self):
        ex = ServerExecutor()
        params = _make_params()
        with patch("platform_mcp.skills.server.executor.ssh_connection", side_effect=OSError("conn refused")):
            result = await ex.execute_command(params, "ls")
        assert result.success is False
        assert "conn refused" in (result.error_message or "")


class TestValidateRemotePath:
    def test_forbidden_path_blocks(self):
        ex = ServerExecutor()
        params = _make_params(forbidden_paths=["/etc"])
        with pytest.raises(PathSecurityError):
            ex._validate_remote_path("/etc/passwd", params, for_write=True)

    def test_not_in_allowed_paths_blocks(self):
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])
        with pytest.raises(PathSecurityError):
            ex._validate_remote_path("/opt/data", params, for_write=True)

    def test_in_allowed_paths_passes(self):
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp", "/home/user"])
        ex._validate_remote_path("/tmp/test.txt", params, for_write=True)

    def test_prefix_match_passes(self):
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/home/user"])
        ex._validate_remote_path("/home/user/data/file.txt", params, for_write=False)


class TestValidateLocalPath:
    def test_nonexistent_local_path_blocks(self, tmp_path):
        ex = ServerExecutor()
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.env = "dev"
            gs.return_value.datasource.allowed_sql_dirs = [str(tmp_path)]
            with pytest.raises(PathSecurityError):
                ex._validate_local_path(str(tmp_path / "missing.txt"), must_exist=True)

    def test_nonexistent_local_path_error_includes_transfer_guidance(self, tmp_path):
        """BUG20260814163941 补充：缺文件报错内嵌 /transfer 中转编排指引（驱动 CC 自纠）"""
        ex = ServerExecutor()
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.env = "dev"
            gs.return_value.datasource.allowed_sql_dirs = [str(tmp_path)]
            with pytest.raises(PathSecurityError, match="transfer/upload") as ei:
                ex._validate_local_path(r"D:\workstation\pkg.zip", must_exist=True)
        assert "staged_path" in str(ei.value)
        assert "PLATFORM_MCP_API_KEY" in str(ei.value)

    def test_outside_whitelist_blocks(self, tmp_path):
        ex = ServerExecutor()
        f = tmp_path / "inroot.txt"
        f.write_text("x")
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.env = "dev"
            gs.return_value.datasource.allowed_sql_dirs = [str(tmp_path / "other_dir")]
            gs.return_value.datasource.sftp_exchange_dir = str(tmp_path / "exchange")
            with pytest.raises(PathSecurityError):
                ex._validate_local_path(str(f), must_exist=True)

    def test_prod_target_empty_whitelist_blocks(self, tmp_path):
        """BUG20260814163941 BUG-2：PROD 目标服务器 + 空白名单 → 拦截"""
        ex = ServerExecutor()
        f = tmp_path / "anywhere.txt"
        f.write_text("x")
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.env = "dev"  # 部署环境 DEV，目标 PROD 仍应拦截
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(tmp_path / "exchange")
            with pytest.raises(PathSecurityError, match="必须配置 allowed_sql_dirs"):
                ex._validate_local_path(str(f), must_exist=True, env_code="PROD")

    def test_prod_deploy_dev_target_allows(self, tmp_path):
        """BUG-2 核心场景：PROD 部署（settings.env=prod）操作 DEV 目标不拦截"""
        ex = ServerExecutor()
        f = tmp_path / "devtarget.txt"
        f.write_text("x")
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.env = "prod"
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(tmp_path / "exchange")
            path = ex._validate_local_path(str(f), must_exist=True, env_code="DEV")
            assert path.exists()

    def test_exchange_dir_exempt_from_whitelist(self, tmp_path):
        """BUG20260814163941：中转目录豁免白名单（PROD 目标 + 空白名单仍可用中转链路）"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        ex = ServerExecutor()
        exchange = tmp_path / "exchange"
        tid = _transfer.new_transfer_id()
        staged = exchange / tid / "pkg.zip"
        staged.parent.mkdir(parents=True)
        staged.write_text("zipped")
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            path = ex._validate_local_path(str(staged), must_exist=True, env_code="PROD")
            assert path == staged.resolve()
        _transfer.reset_exchange_dir_cache()


class TestValidateRemotePathEnvSemantics:
    def test_prod_target_empty_allowed_paths_blocks(self):
        """BUG-2：PROD 目标 + 未配置 allowed_paths → 拦截（原按部署环境判定，误伤 DEV 目标）"""
        ex = ServerExecutor()
        params = _make_params(allowed_paths=None)
        params.env_code = "PROD"
        with pytest.raises(PathSecurityError, match="PROD"):
            ex._validate_remote_path("/data/x.zip", params, for_write=True)

    def test_dev_target_empty_allowed_paths_allows_even_in_prod_deploy(self):
        """BUG-2：PROD 部署操作 DEV 目标（未配置 allowed_paths）→ 放行"""
        import os

        ex = ServerExecutor()
        params = _make_params(allowed_paths=None)
        params.env_code = "DEV"
        old = os.environ.get("PLATFORM_MCP_ENV")
        os.environ["PLATFORM_MCP_ENV"] = "prod"  # 旧实现此处会误拦
        try:
            ex._validate_remote_path("/data/x.zip", params, for_write=True)
        finally:
            if old is None:
                os.environ.pop("PLATFORM_MCP_ENV", None)
            else:
                os.environ["PLATFORM_MCP_ENV"] = old


class TestUploadStagedCleanup:
    """BUG20260814163941 BUG-5：上传成功/失败后自动清理中转任务目录"""

    def _stage(self, exchange, filename="pkg.zip"):
        from platform_mcp.skills.server import transfer as _transfer

        tid = _transfer.new_transfer_id()
        staged = exchange / tid / filename
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"data")
        return tid, staged

    @pytest.mark.asyncio
    async def test_upload_success_cleans_staged_dir(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange)
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is True
        assert not staged.parent.exists()  # 中转任务目录已清理
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_upload_failure_cleans_staged_dir(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange)
        ex = ServerExecutor()
        params = _make_params(allowed_paths=None)
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection",
                      side_effect=OSError("ssh refused")):
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is False
        assert not staged.parent.exists()  # 失败同样清理
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_upload_non_staged_local_kept(self, tmp_path):
        """非中转路径（普通白名单文件）上传后不清理"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        normal = tmp_path / "normal.txt"
        normal.write_bytes(b"data")
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = [str(tmp_path)]
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(normal), "/data/normal.txt")
        assert result.success is True
        assert normal.exists()  # 白名单普通文件不清理
        _transfer.reset_exchange_dir_cache()


class TestDownloadStagedLifecycle:
    """下载链路中转文件生命周期 — BUG20260814163941 BUG-4/5

    成功：保留（CC 经 GET /transfer/download 取回后显式 DELETE，未取回 TTL 兜底）
    失败：立即清理部分写入的中转文件
    """

    def _staged_target(self, exchange, filename="fetched.zip"):
        from platform_mcp.skills.server import transfer as _transfer

        tid = _transfer.new_transfer_id()
        return exchange / tid / filename

    @pytest.mark.asyncio
    async def test_download_success_keeps_staged_for_cc_fetch(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        staged = self._staged_target(exchange)
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.stat = AsyncMock(return_value=MagicMock(size=100))
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is True
        assert staged.parent.exists()  # 成功后保留，等 CC 取回
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_download_failure_cleans_partial_staged(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        staged = self._staged_target(exchange)
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection",
                      side_effect=OSError("ssh refused")):
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is False
        assert not staged.parent.exists()  # 失败即清理部分写入
        _transfer.reset_exchange_dir_cache()


class TestFileSizeLimits:
    def test_max_file_size_is_500mb(self):
        assert _MAX_FILE_SIZE_BYTES == 500 * 1024 * 1024

    def test_max_command_input_is_100kb(self):
        from platform_mcp.skills.server.executor import _MAX_COMMAND_INPUT_BYTES
        assert _MAX_COMMAND_INPUT_BYTES == 100 * 1024

    @pytest.mark.asyncio
    async def test_execute_command_超长_拒绝(self):
        """命令长度 > 100KB 时返回失败，不发 SSH 请求"""
        from platform_mcp.skills.server.executor import _MAX_COMMAND_INPUT_BYTES
        ex = ServerExecutor()
        long_cmd = "echo " + "a" * (_MAX_COMMAND_INPUT_BYTES + 10)
        params = _make_params()
        result = await ex.execute_command(params, long_cmd)
        assert result.success is False
        assert "超过" in (result.error_message or "") or "KB" in (result.error_message or "")
