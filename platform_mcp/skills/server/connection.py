"""SSH/SFTP ephemeral 连接 — asynccontextmanager（镜像 skills/database/connection.py）"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from platform_mcp.server.manager import ServerConnParams


@asynccontextmanager
async def ssh_connection(params: ServerConnParams) -> AsyncIterator:
    """建立 SSH 连接，yield asyncssh.SSHClientConnection。

    known_hosts=None 跳过 host key 校验（一期简化，与 plink 首次接受 host key 等价）。
    生产环境后续可改为 known_hosts=<path> 强校验。
    """
    import asyncssh

    connect_kwargs: dict = {
        "host": params.host,
        "port": params.ssh_port,
        "username": params.username,
        "known_hosts": None,
        "connect_timeout": 30,
    }
    if params.ssh_key_bytes:
        connect_kwargs["client_keys"] = [asyncssh.import_private_key(params.ssh_key_bytes.decode("utf-8"))]
    elif params.password:
        connect_kwargs["password"] = params.password
    else:
        raise ValueError("SSH 连接需提供 password 或 ssh_key_bytes")

    conn = await asyncssh.connect(**connect_kwargs)
    try:
        yield conn
    finally:
        try:
            conn.close()
            await conn.wait_closed()
        except Exception:
            pass


@asynccontextmanager
async def sftp_connection(params: ServerConnParams) -> AsyncIterator:
    """建立 SSH + SFTP 双通道，yield asyncssh.SFTPClient。

    复用 ssh_connection 取得 SSH 连接，再 start_sftp_client()。
    退出时同步关闭 SFTP + SSH。
    """
    async with ssh_connection(params) as conn:
        sftp = await conn.start_sftp_client()
        try:
            yield sftp
        finally:
            try:
                sftp.exit()
            except Exception:
                pass


__all__ = ["ssh_connection", "sftp_connection"]
