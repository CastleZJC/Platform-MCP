"""server skill 执行器 — SSH 命令执行 + SFTP 文件传输 + 路径安全校验

镜像 skills/database/executor.py 的结构与异常处理风格。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.mcp_server.skill.concurrency import ConcurrencyLimiter
from platform_mcp.server.manager import ServerConnParams
from platform_mcp.skills.server.connection import sftp_connection, ssh_connection
from platform_mcp.skills.server.transfer import get_exchange_dir, maybe_cleanup_staged


_MAX_COMMAND_INPUT_BYTES = 100 * 1024  # 100KB 命令输入上限（防范超长命令注入/DoS）
_MAX_COMMAND_OUTPUT_BYTES = 1024 * 1024  # 1MB stdout/stderr 截断（≥100KB 满足回显需求）
_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500MB 文件大小上限（plan §三 500MB）
_MAX_TRANSFER_ATTEMPTS = 3  # 网络中断自动重试次数（断点续传，含首次共 3 次尝试；全部失败才判失败并清理）

# BUG20260814163941 复核（2026-08-17）：Windows 工作站路径识别（任意字母盘符 X:\ / X:/，含 C/D/E/F…，或 UNC \\server）
_WIN_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")
# 宿主机是否 Windows（DEV 本机部署时工作站路径即宿主机路径，可直接读写，跳过拦截）
_HOST_IS_WINDOWS = os.name == "nt"

_concurrency_limiter = ConcurrencyLimiter()


def _looks_like_windows_path(local_path: str) -> bool:
    return bool(_WIN_PATH_PATTERN.match(local_path.strip()))


def _win_path_basename(local_path: str) -> str:
    return local_path.replace("\\", "/").rsplit("/", 1)[-1]


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
        except Exception as e:
            # 校验失败（路径/白名单/大小）：staged 文件已无意义，清理
            maybe_cleanup_staged(local_path)
            return TransferResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        last_error: Exception | None = None
        for attempt in range(1, _MAX_TRANSFER_ATTEMPTS + 1):
            try:
                async with _concurrency_limiter.acquire(params.server_code, params.max_concurrent):
                    async with sftp_connection(params) as sftp:
                        # 断点续传上传：远端已有 partial 时从断点续写（每次尝试都不重头传）
                        remote_size = await self._sftp_put_resumable(sftp, local, remote_path, file_size)
                        if remote_size != file_size:
                            raise PathSecurityError(
                                f"上传完整性校验失败: 远端 {remote_size}B ≠ 本地 {file_size}B"
                                "（传输可能被截断），请重试"
                            )
                # 上传成功才清理中转任务目录
                maybe_cleanup_staged(local_path)
                return TransferResult(
                    success=True,
                    bytes_transferred=file_size,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            except Exception as e:
                last_error = e
                if attempt < _MAX_TRANSFER_ATTEMPTS:
                    logger.warning(
                        "sftp upload 第 {}/{} 次尝试失败，断点续传重试: {}",
                        attempt, _MAX_TRANSFER_ATTEMPTS, e,
                    )
                    continue
                break

        # 3 次尝试均失败：终止 + 失败 + 清理中转文件
        maybe_cleanup_staged(local_path)
        logger.warning(
            "sftp upload 失败（{} 次尝试均失败）: {}", _MAX_TRANSFER_ATTEMPTS, last_error
        )
        return TransferResult(
            success=False,
            error_message=str(last_error),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

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
        except Exception as e:
            # 校验失败：本地无 partial 落地，但 staged 目录已无意义，清理
            maybe_cleanup_staged(local_path)
            return TransferResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        last_error: Exception | None = None
        for attempt in range(1, _MAX_TRANSFER_ATTEMPTS + 1):
            try:
                async with _concurrency_limiter.acquire(params.server_code, params.max_concurrent):
                    async with sftp_connection(params) as sftp:
                        remote_attrs = await sftp.stat(remote_path)
                        file_size = remote_attrs.size or 0
                        if file_size > _MAX_FILE_SIZE_BYTES:
                            raise PathSecurityError(
                                f"远端文件超过 {_MAX_FILE_SIZE_BYTES // 1024 // 1024}MB 限制: {remote_path}"
                            )
                        # 断点续传下载：本地已有 partial 时从断点续写（每次尝试都不重头传）
                        actual_size = await self._sftp_get_resumable(sftp, remote_path, local, file_size)
                        if actual_size != file_size:
                            raise PathSecurityError(
                                f"下载完整性校验失败: 本地 {actual_size}B ≠ 远端 {file_size}B"
                                "（传输可能被截断），请重试"
                            )
                # 下载成功保留 staged 供 CC 经 HTTP 取回（取回后 CC 显式 DELETE /transfer/{tid}）
                return TransferResult(
                    success=True,
                    bytes_transferred=file_size,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            except Exception as e:
                last_error = e
                if attempt < _MAX_TRANSFER_ATTEMPTS:
                    logger.warning(
                        "sftp download 第 {}/{} 次尝试失败，断点续传重试: {}",
                        attempt, _MAX_TRANSFER_ATTEMPTS, e,
                    )
                    continue
                break

        # 3 次尝试均失败：终止 + 失败 + 清理本地 partial
        maybe_cleanup_staged(local_path)
        logger.warning(
            "sftp download 失败（{} 次尝试均失败）: {}", _MAX_TRANSFER_ATTEMPTS, last_error
        )
        return TransferResult(
            success=False,
            error_message=str(last_error),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def _sftp_put_resumable(
        self, sftp: Any, local: Path, remote_path: str, file_size: int
    ) -> int:
        """分片续传上传：远端已有 partial 时从断点续写，返回远端最终大小。

        remote_path 为已存在目录时实际落点是 <dir>/<basename>（与 put 一致），
        续传前先解析实际落点；mode "r+b"（READ|WRITE 不截断）续写、"wb" 覆盖。
        """
        remote_target = remote_path
        if await sftp.isdir(remote_path):
            remote_target = remote_path.rstrip("/\\") + "/" + local.name

        remote_size = 0
        try:
            remote_size = (await sftp.stat(remote_target)).size or 0
        except Exception:
            remote_size = 0

        if 0 < remote_size < file_size:
            mode, offset = "r+b", remote_size
        else:
            mode, offset = "wb", 0

        block = 1024 * 1024
        async with sftp.open(remote_target, mode) as remote_f:
            if offset:
                await remote_f.seek(offset)
            with open(local, "rb") as local_f:
                local_f.seek(offset)
                while True:
                    chunk = local_f.read(block)
                    if not chunk:
                        break
                    await remote_f.write(chunk)

        return (await sftp.stat(remote_target)).size or 0

    async def _sftp_get_resumable(
        self, sftp: Any, remote_path: str, local: Path, file_size: int
    ) -> int:
        """分片续传下载：本地已有 partial 时从断点续写，返回本地最终大小。

        本地 mode "ab" 追加续写、"wb" 覆盖；远端读句柄 seek 到断点。
        """
        local_size = local.stat().st_size if local.exists() else 0

        if 0 < local_size < file_size:
            mode, offset = "ab", local_size
        else:
            mode, offset = "wb", 0

        block = 1024 * 1024
        async with sftp.open(remote_path, "rb") as remote_f:
            if offset:
                await remote_f.seek(offset)
            with open(local, mode) as local_f:
                while True:
                    chunk = await remote_f.read(block)
                    if not chunk:
                        break
                    local_f.write(chunk)

        return local.stat().st_size

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

        # BUG20260814163941 复核（2026-08-17）：Windows 工作站路径前置识别。
        # Linux 宿主（PROD）无法读写工作站路径，此前报"本地文件不存在"误导用户；
        # 现改为明确告知工作站路径语义 + 中转编排指引，驱动 CC 自动切换传输方式。
        # Windows 宿主（DEV 本机部署）本身可读写工作站路径，跳过此拦截。
        if not _HOST_IS_WINDOWS and _looks_like_windows_path(local_path):
            filename = _win_path_basename(local_path)
            if must_exist:
                raise PathSecurityError(
                    f"检测到 Windows 工作站路径: {local_path}。MCP 服务器无法直接读取工作站本地文件，"
                    "请先中转到 MCP 服务器后重试："
                    'curl -H "PLATFORM_MCP_API_KEY: <key>" '
                    f'--data-binary @"{local_path}" '
                    f'"http://<MCP服务器地址>:9000/transfer/upload?filename={filename}"，'
                    "成功后将响应 JSON 中的 staged_path 作为 local_path 重新调用 upload_file"
                )
            raise PathSecurityError(
                f"检测到 Windows 工作站路径: {local_path}。MCP 服务器无法直接写入工作站路径，"
                "请改用中转目录下载：先 GET \"http://<MCP服务器地址>:9000/transfer/info\" 获取中转目录，"
                "以 <中转目录>/<新生成uuid4>/<文件名> 作为 local_path 调用 download_file，"
                '成功后 curl -H "PLATFORM_MCP_API_KEY: <key>" '
                f'-o "{local_path}" '
                '"http://<MCP服务器地址>:9000/transfer/download/<transfer_id>/<文件名>" 取回工作站，'
                '最后 DELETE "http://<MCP服务器地址>:9000/transfer/<transfer_id>" 清理'
            )

        path = Path(local_path).resolve()
        if must_exist and not path.exists():
            # BUG20260814163941 补充修复：CC 常把工作站路径直传 local_path；报错内嵌
            # 中转编排指引驱动 CC 自纠（description 驱动实测不可靠，错误驱动可靠）
            raise PathSecurityError(
                f"本地文件不存在: {local_path}。若该文件在用户工作站本地，请先中转到 MCP 服务器："
                'curl -H "PLATFORM_MCP_API_KEY: <key>" --data-binary @<工作站文件> '
                '"http://<MCP服务器地址>/transfer/upload?filename=<文件名>"，'
                "将响应中的 staged_path 作为 local_path 重新调用 upload_file"
            )
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
