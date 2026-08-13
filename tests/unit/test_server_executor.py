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

    def test_outside_whitelist_blocks(self, tmp_path):
        ex = ServerExecutor()
        f = tmp_path / "inroot.txt"
        f.write_text("x")
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.env = "dev"
            gs.return_value.datasource.allowed_sql_dirs = [str(tmp_path / "other_dir")]
            with pytest.raises(PathSecurityError):
                ex._validate_local_path(str(f), must_exist=True)


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
