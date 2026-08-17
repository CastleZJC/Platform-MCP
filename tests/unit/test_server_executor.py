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


def _fake_sftp_handle():
    """构造支持 async with 的 SFTP 文件句柄 mock（seek/write/read 均 awaitable）。"""
    handle = AsyncMock()
    handle.__aenter__ = AsyncMock(return_value=handle)
    handle.__aexit__ = AsyncMock(return_value=None)
    handle.seek = AsyncMock(return_value=0)
    handle.write = AsyncMock(return_value=0)
    handle.read = AsyncMock(return_value=b"")
    return handle


def _upload_sftp(remote_partial=0, final_size=4, isdir=False):
    """上传方向 sftp mock：stat 首次返回远端 partial，之后返回 final_size。

    _sftp_put_resumable 会 stat 两次（查已有 + 返回最终大小）。
    """
    sftp = AsyncMock()
    sftp.isdir = AsyncMock(return_value=isdir)
    sftp.open = MagicMock(return_value=_fake_sftp_handle())

    stat_sizes = iter([remote_partial, final_size, final_size, final_size])

    async def _stat(p):
        try:
            return MagicMock(size=next(stat_sizes))
        except StopIteration:
            return MagicMock(size=final_size)

    sftp.stat = AsyncMock(side_effect=_stat)
    return sftp


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
            sftp_mock = _upload_sftp(remote_partial=0, final_size=4)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is True
        assert not staged.parent.exists()  # 中转任务目录已清理（成功才清理）
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_upload_failure_cleans_staged_dir_after_retries(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange)
        ex = ServerExecutor()
        params = _make_params(allowed_paths=None)
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection",
                      side_effect=OSError("ssh refused")) as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is False
        assert mock_sftp.call_count == 3  # 网络中断自动重试 3 次
        assert not staged.parent.exists()  # 3 次均失败 → 终止 + 清理中转
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
            sftp_mock = _upload_sftp(remote_partial=0, final_size=4)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(normal), "/data/normal.txt")
        assert result.success is True
        assert normal.exists()  # 白名单普通文件不清理
        _transfer.reset_exchange_dir_cache()


class TestDownloadStagedLifecycle:
    """下载链路中转文件生命周期 — BUG20260814163941 BUG-4/5

    成功：保留（CC 经 GET /transfer/download 取回后显式 DELETE，未取回 TTL 兜底）
    失败：网络中断自动重试 3 次（断点续传），全部失败后清理部分写入的中转文件
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
            handle = _fake_sftp_handle()
            handle.read = AsyncMock(side_effect=[b"x" * 100, b""])
            sftp_mock.open = MagicMock(return_value=handle)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is True
        assert staged.parent.exists()  # 成功后保留，等 CC 取回
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_download_failure_cleans_partial_after_retries(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        staged = self._staged_target(exchange)
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection",
                      side_effect=OSError("ssh refused")) as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is False
        assert mock_sftp.call_count == 3  # 网络中断自动重试 3 次
        assert not staged.parent.exists()  # 3 次均失败 → 终止 + 清理 partial
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


# ============================================================
# BUG20260814163941 复核（2026-08-17）：
# 1) Windows 工作站路径前置识别 → 中转编排指引（不再误报"本地文件不存在"）
# 2) SFTP 传输后尺寸完整性校验（大文件截断必须显式失败）
# ============================================================


class TestWindowsWorkstationPathGuidance:
    """win 路径（Linux 宿主）→ 返回中转编排指引而非"本地文件不存在"。"""

    def test_upload_win路径_返回中转指引(self):
        ex = ServerExecutor()
        win_path = r"D:\workstation\deploy\pkg.zip"
        with patch("platform_mcp.skills.server.executor._HOST_IS_WINDOWS", False):
            with pytest.raises(PathSecurityError, match="工作站"):
                ex._validate_local_path(win_path, must_exist=True, env_code="DEV")

    def test_upload_win路径_指引含curl与staged_path(self):
        ex = ServerExecutor()
        win_path = "D:/claude/deploy_zip/core.zip"
        with patch("platform_mcp.skills.server.executor._HOST_IS_WINDOWS", False):
            with pytest.raises(PathSecurityError) as exc_info:
                ex._validate_local_path(win_path, must_exist=True, env_code="DEV")
        msg = str(exc_info.value)
        assert "PLATFORM_MCP_API_KEY" in msg
        assert "/transfer/upload" in msg
        assert "filename=core.zip" in msg
        assert "staged_path" in msg
        assert "本地文件不存在" not in msg

    def test_download_win路径_返回中转取回指引(self):
        ex = ServerExecutor()
        with patch("platform_mcp.skills.server.executor._HOST_IS_WINDOWS", False):
            with pytest.raises(PathSecurityError) as exc_info:
                ex._validate_local_path(r"D:\data\fetched.zip", must_exist=False, env_code="DEV")
        msg = str(exc_info.value)
        assert "/transfer/info" in msg
        assert "/transfer/download" in msg
        assert "DELETE" in msg

    def test_windows宿主_不拦截win路径(self, tmp_path):
        """DEV 本机部署（宿主即 Windows）时工作站路径合法，走正常校验流程"""
        ex = ServerExecutor()
        local = tmp_path / "ok.txt"
        local.write_bytes(b"x")
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.datasource.allowed_sql_dirs = []
            with patch("platform_mcp.skills.server.executor._HOST_IS_WINDOWS", True):
                path = ex._validate_local_path(str(local), must_exist=True, env_code="DEV")
        assert path is not None


class TestTransferIntegrityVerification:
    """SFTP 传输后尺寸校验 —— 截断必须显式失败并清理中转。"""

    def _stage(self, exchange, filename="pkg.zip"):
        from platform_mcp.skills.server import transfer as _transfer

        tid = _transfer.new_transfer_id()
        staged = exchange / tid / filename
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"data")
        return tid, staged

    @pytest.mark.asyncio
    async def test_upload_远端尺寸不符_失败并清理中转(self, tmp_path):
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
            # 远端最终 stat 尺寸 < 本地 → 模拟截断
            sftp_mock = _upload_sftp(remote_partial=0, final_size=2)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is False
        assert "完整性校验失败" in (result.error_message or "")
        assert not staged.parent.exists()  # 截断重试 3 次均失败 → 清理中转
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_upload_远端尺寸一致_成功(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange)  # 4 字节
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = _upload_sftp(remote_partial=0, final_size=4)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is True
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_upload_远端目录路径_stat实际落点(self, tmp_path):
        """remote_path 为已存在目录时，续传解析实际落点 <目录>/<basename>，
        完整性校验必须 stat 实际落点，不得误判目录尺寸"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange)  # pkg.zip, 4 字节
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.isdir = AsyncMock(return_value=True)  # 远端是目录
            sftp_mock.open = MagicMock(return_value=_fake_sftp_handle())
            stat_calls = []

            async def _stat(p):
                stat_calls.append(p)
                return MagicMock(size=4) if p.endswith("pkg.zip") else MagicMock(size=4096)

            sftp_mock.stat = AsyncMock(side_effect=_stat)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/deploy/")
        assert result.success is True
        assert stat_calls == ["/data/deploy/pkg.zip", "/data/deploy/pkg.zip"]
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_download_本地尺寸不符_失败并清理partial(self, tmp_path):
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid = _transfer.new_transfer_id()
        staged = exchange / tid / "fetched.zip"
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])

        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.stat = AsyncMock(return_value=MagicMock(size=4096))  # 远端声明 4KB
            handle = _fake_sftp_handle()
            handle.read = AsyncMock(return_value=b"")  # 模拟截断：读不到数据
            sftp_mock.open = MagicMock(return_value=handle)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is False
        assert "完整性校验失败" in (result.error_message or "")
        assert not staged.exists()  # 截断重试 3 次均失败 → 清理 partial
        _transfer.reset_exchange_dir_cache()


class TestResumableTransfer:
    """断点续传：远端/本地已有 partial 时从断点续写，而非重头传。"""

    def _stage(self, exchange, filename="pkg.zip", data=b"data"):
        from platform_mcp.skills.server import transfer as _transfer

        tid = _transfer.new_transfer_id()
        staged = exchange / tid / filename
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        return tid, staged

    @pytest.mark.asyncio
    async def test_upload_远端partial_续传seek断点(self, tmp_path):
        """远端已有 2 字节 partial 时，用 "r+b" 续写 + seek(2) 而非 "wb" 覆盖"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange, data=b"abcd")  # 本地 4 字节
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.isdir = AsyncMock(return_value=False)
            handle = _fake_sftp_handle()
            sftp_mock.open = MagicMock(return_value=handle)
            # 第一次 stat 返回 partial=2，第二次返回 final=4
            sftp_mock.stat = AsyncMock(side_effect=[MagicMock(size=2), MagicMock(size=4)])
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is True
        # 续传模式：open 用 "r+b"（不截断），seek 到断点 2
        assert sftp_mock.open.call_args[0][1] == "r+b"
        handle.seek.assert_awaited_with(2)
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_upload_远端完整_覆盖重传(self, tmp_path):
        """远端已有完整尺寸（>= 本地）时用 "wb" 覆盖，避免追加污染"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange, data=b"abcd")  # 本地 4 字节
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.isdir = AsyncMock(return_value=False)
            handle = _fake_sftp_handle()
            sftp_mock.open = MagicMock(return_value=handle)
            # 远端已有 4 字节（>= 本地 4）→ 覆盖
            sftp_mock.stat = AsyncMock(side_effect=[MagicMock(size=4), MagicMock(size=4)])
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is True
        assert sftp_mock.open.call_args[0][1] == "wb"
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_download_本地partial_续传追加(self, tmp_path):
        """本地已有 2 字节 partial 时，远端 seek(2) + 本地追加，最终拼接完整"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid = _transfer.new_transfer_id()
        staged = exchange / tid / "fetched.zip"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"ab")  # 本地已有 partial 2 字节
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.stat = AsyncMock(return_value=MagicMock(size=4))  # 远端 4 字节
            handle = _fake_sftp_handle()
            handle.read = AsyncMock(side_effect=[b"cd", b""])  # 从断点读到剩余 2 字节
            sftp_mock.open = MagicMock(return_value=handle)
            mock_sftp.return_value.__aenter__ = AsyncMock(return_value=sftp_mock)
            mock_sftp.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is True
        handle.seek.assert_awaited_with(2)  # 远端从断点 2 读
        assert staged.read_bytes() == b"abcd"  # partial + 续传 = 完整
        _transfer.reset_exchange_dir_cache()


class TestTransferRetry:
    """网络中断自动重试（断点续传）：前 N 次失败不判失败，重试至成功或 3 次耗尽。

    用户语义：遇到网络中断自动重试 3 次，每次断点续传、不做失败处理；
    3 次均失败才终止 + 失败 + 清理中转文件。
    """

    def _stage(self, exchange, filename="pkg.zip", data=b"data"):
        from platform_mcp.skills.server import transfer as _transfer

        tid = _transfer.new_transfer_id()
        staged = exchange / tid / filename
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        return tid, staged

    @pytest.mark.asyncio
    async def test_upload_retries_then_succeeds(self, tmp_path):
        """前 2 次 sftp_connection 抛 OSError（网络中断），第 3 次成功 → 成功 + 清理"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid, staged = self._stage(exchange, data=b"abcd")
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/data"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = _upload_sftp(remote_partial=0, final_size=4)
            working_ctx = AsyncMock()
            working_ctx.__aenter__ = AsyncMock(return_value=sftp_mock)
            working_ctx.__aexit__ = AsyncMock(return_value=None)
            calls = {"n": 0}

            def _side_effect(_params):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise OSError("ssh refused")
                return working_ctx

            mock_sftp.side_effect = _side_effect
            result = await ex.upload_file(params, str(staged), "/data/pkg.zip")
        assert result.success is True
        assert calls["n"] == 3  # 前 2 次中断重试，第 3 次成功
        assert not staged.parent.exists()  # 成功后清理中转
        _transfer.reset_exchange_dir_cache()

    @pytest.mark.asyncio
    async def test_download_retries_then_succeeds(self, tmp_path):
        """前 2 次 sftp_connection 抛 OSError，第 3 次成功 → 成功 + 保留供 CC 取回"""
        from platform_mcp.skills.server import transfer as _transfer

        _transfer.reset_exchange_dir_cache()
        exchange = tmp_path / "exchange"
        exchange.mkdir()
        tid = _transfer.new_transfer_id()
        staged = exchange / tid / "fetched.zip"
        ex = ServerExecutor()
        params = _make_params(allowed_paths=["/tmp"])
        with patch("platform_mcp.config.get_settings") as gs, \
                patch("platform_mcp.skills.server.executor.sftp_connection") as mock_sftp:
            gs.return_value.datasource.allowed_sql_dirs = []
            gs.return_value.datasource.sftp_exchange_dir = str(exchange)
            sftp_mock = AsyncMock()
            sftp_mock.stat = AsyncMock(return_value=MagicMock(size=100))
            handle = _fake_sftp_handle()
            handle.read = AsyncMock(side_effect=[b"x" * 100, b""])
            sftp_mock.open = MagicMock(return_value=handle)
            working_ctx = AsyncMock()
            working_ctx.__aenter__ = AsyncMock(return_value=sftp_mock)
            working_ctx.__aexit__ = AsyncMock(return_value=None)
            calls = {"n": 0}

            def _side_effect(_params):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise OSError("ssh refused")
                return working_ctx

            mock_sftp.side_effect = _side_effect
            result = await ex.download_file(params, "/tmp/fetched.zip", str(staged))
        assert result.success is True
        assert calls["n"] == 3
        assert staged.parent.exists()  # 下载成功保留供 CC 取回
        _transfer.reset_exchange_dir_cache()
