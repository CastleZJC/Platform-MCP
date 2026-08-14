"""server skill 执行器 — SSH 命令执行 + SFTP 文件传输 + 路径安全校验

镜像 skills/database/executor.py 的结构与异常处理风格。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.mcp_server.skill.concurrency import ConcurrencyLimiter
from platform_mcp.server.manager import ServerConnParams
from platform_mcp.skills.server.connection import sftp_connection, ssh_connection
from platform_mcp.skills.server.transfer import get_exchange_dir, maybe_cleanup_staged


_MAX_COMMAND_INPUT_BYTES = 100 * 1024  # 100KB 命令输入上限（防范超长命令注入/DoS）
_MAX_COMMAND_OUTPUT_BYTES = 1024 * 1024  # 1MB stdout/stderr 截断（≥100KB 满足回显需求）
_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500MB 文件大小上限（plan §三 500MB）

_concurrency_limiter = ConcurrencyLimiter()


@dataclass
class CommandResult:
    success: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    error_message: str | None = None
    truncated: bool = False
    source_session: dict | None = None


@dataclass
class TransferResult:
    success: bool
    bytes_transferred: int = 0
    duration_ms: int = 0
    error_message: str | None = None
    source_session: dict | None = None


class ServerExecutor:

    async def execute_command(
        self,
        params: ServerConnParams,
        command: str,
        timeout: int | None = None,
    ) -> CommandResult:
        timeout = timeout or params.command_timeout
        start = time.monotonic()
        if len(command) > _MAX_COMMAND_INPUT_BYTES:
            return CommandResult(
                success=False,
                error_message=(
                    f"命令长度 {len(command)} 超过 {_MAX_COMMAND_INPUT_BYTES // 1024}KB 限制"
                ),
                duration_ms=0,
            )
        try:
            async with _concurrency_limiter.acquire(params.server_code, params.max_concurrent):
                async with ssh_connection(params) as conn:
                    wrapped = f"echo $$; exec {command}"
                    result = await asyncio.wait_for(
                        conn.run(wrapped, check=False, timeout=timeout),
                        timeout=timeout + 30,  # 留 30s 余量给 SSH 协议
                    )
            stdout = (result.stdout or "")
            stderr = (result.stderr or "")
            source_session: dict | None = None
            newline_idx = stdout.find("\n")
            if newline_idx > 0:
                first_line = stdout[:newline_idx].strip()
                if first_line.isdigit():
                    source_session = {"type": "linux", "pid": int(first_line)}
                    stdout = stdout[newline_idx + 1:]
            truncated = False
            if len(stdout) > _MAX_COMMAND_OUTPUT_BYTES:
                stdout = stdout[:_MAX_COMMAND_OUTPUT_BYTES]
                truncated = True
            if len(stderr) > _MAX_COMMAND_OUTPUT_BYTES:
                stderr = stderr[:_MAX_COMMAND_OUTPUT_BYTES]
                truncated = True
            return CommandResult(
                success=result.exit_status == 0,
                exit_code=result.exit_status,
                stdout=stdout,
                stderr=stderr,
                duration_ms=int((time.monotonic() - start) * 1000),
                truncated=truncated,
                source_session=source_session,
            )
        except asyncio.TimeoutError:
            return CommandResult(
                success=False,
                error_message=f"命令执行超时 ({timeout}s)",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

    async def upload_file(
        self,
        params: ServerConnParams,
        local_path: str,
        remote_path: str,
    ) -> TransferResult:
        start = time.monotonic()
        try:
            local = self._validate_local_path(local_path, must_exist=True, env_code=params.env_code)
            self._validate_remote_path(remote_path, params, for_write=True)
            file_size = local.stat().st_size
            if file_size > _MAX_FILE_SIZE_BYTES:
                raise PathSecurityError(
                    f"文件超过 {_MAX_FILE_SIZE_BYTES // 1024 // 1024}MB 限制: {local_path}"
                )

            async with _concurrency_limiter.acquire(params.server_code, params.max_concurrent):
                async with sftp_connection(params) as sftp:
                    await sftp.put(str(local), remote_path)

            return TransferResult(
                success=True,
                bytes_transferred=file_size,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            logger.warning("sftp upload failed: {}", e)
            return TransferResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            # BUG20260814163941 BUG-5：上传成功/失败均清理中转任务目录（仅自身 transfer_id）
            maybe_cleanup_staged(local_path)

    async def download_file(
        self,
        params: ServerConnParams,
        remote_path: str,
        local_path: str,
    ) -> TransferResult:
        start = time.monotonic()
        try:
            local = self._validate_local_path(local_path, must_exist=False, env_code=params.env_code)
            self._validate_remote_path(remote_path, params, for_write=False)
            local.parent.mkdir(parents=True, exist_ok=True)

            async with _concurrency_limiter.acquire(params.server_code, params.max_concurrent):
                async with sftp_connection(params) as sftp:
                    remote_attrs = await sftp.stat(remote_path)
                    file_size = remote_attrs.size or 0
                    if file_size > _MAX_FILE_SIZE_BYTES:
                        raise PathSecurityError(
                            f"远端文件超过 {_MAX_FILE_SIZE_BYTES // 1024 // 1024}MB 限制: {remote_path}"
                        )
                    await sftp.get(remote_path, str(local))

            return TransferResult(
                success=True,
                bytes_transferred=file_size,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            logger.warning("sftp download failed: {}", e)
            # 下载失败即清理可能部分写入的中转文件（成功时保留，等 CC 经
            # GET /transfer/download 取回后显式 DELETE；未取回由 TTL 30 分钟兜底）
            maybe_cleanup_staged(local_path)
            return TransferResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

    def _validate_local_path(
        self, local_path: str, must_exist: bool = True, env_code: str = "DEV"
    ) -> Path:
        """校验本地路径安全性。

        复用 settings.datasource.allowed_sql_dirs 作为本地白名单（plan §三 决策）。
        BUG20260814163941 BUG-2：拦截语义 = 目标资源环境（pmcp_server.env_code），
        而非 MCP 部署环境（settings.env）——PROD 部署操作 DEV 目标不应被误伤。
        中转目录（BUG20260814163941）为平台自管，天然可信、豁免白名单。
        """
        from platform_mcp.config import get_settings

        settings = get_settings()
        allowed = settings.datasource.allowed_sql_dirs

        path = Path(local_path).resolve()
        if must_exist and not path.exists():
            raise PathSecurityError(f"本地文件不存在: {local_path}")
        if Path(local_path).is_symlink():
            raise PathSecurityError(f"禁止符号链接: {local_path}")

        # 上传：本地是被读取的源文件，必须直接在白名单内
        # 下载：本地是要写入的目标，其父目录必须在白名单内
        check_path = str(path) if must_exist else str(path.parent)
        exchange = str(get_exchange_dir().resolve())
        in_exchange = check_path == exchange or check_path.startswith(exchange + "\\") or check_path.startswith(exchange + "/")

        if not in_exchange:
            if not allowed:
                if env_code == "PROD":
                    raise PathSecurityError(
                        "目标服务器属 PROD 环境，必须配置 allowed_sql_dirs，禁止任意路径执行文件传输"
                    )
                logger.warning(
                    "allowed_sql_dirs 未配置，目标环境={} 允许任意本地路径（PROD 目标强制要求配置）",
                    env_code,
                )
            else:
                allowed_resolved = [str(Path(d).resolve()) for d in allowed]
                if not any(check_path.startswith(d) for d in allowed_resolved):
                    raise PathSecurityError(f"本地路径不在白名单目录内: {local_path}")
        return path

    def _validate_remote_path(
        self,
        remote_path: str,
        params: ServerConnParams,
        for_write: bool,
    ) -> None:
        """校验远端路径在 allowed_paths 白名单内、不在 forbidden_paths 黑名单内。"""
        if params.forbidden_paths:
            for bad in params.forbidden_paths:
                if remote_path.startswith(bad):
                    raise PathSecurityError(f"远端路径在黑名单内: {remote_path} (matched {bad})")

        if params.allowed_paths:
            if not any(remote_path.startswith(p) for p in params.allowed_paths):
                raise PathSecurityError(
                    f"远端路径不在 allowed_paths 白名单内: {remote_path}"
                )
        else:
            if params.env_code == "PROD":
                raise PathSecurityError(
                    "目标服务器属 PROD 环境，必须配置 allowed_paths，禁止任意远端路径"
                )
            logger.warning(
                "server {} 未配置 allowed_paths，允许任意远端路径（PROD 目标强制要求）",
                params.server_code,
            )


server_executor = ServerExecutor()
