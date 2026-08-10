"""服务器连接管理器 — 查询配置、解密凭证、SSH 健康检查（镜像 datasource/manager.py）"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select

from platform_mcp.common import database as _db
from platform_mcp.server.models import PmcpServer


@dataclass
class ServerConnParams:
    server_code: str
    host: str
    ssh_port: int
    username: str
    password: str | None = None        # 与 ssh_key_bytes 二选一
    ssh_key_bytes: bytes | None = None  # 解密后的 PEM 私钥字节
    env_code: str = "DEV"
    max_concurrent: int = 3
    command_timeout: int = 1800
    allowed_paths: list[str] | None = None
    forbidden_paths: list[str] | None = None


def _get_crypto_utils():
    from pathlib import Path

    from platform_mcp.common.crypto import CryptoUtils
    from platform_mcp.config import get_settings

    settings = get_settings()
    key_path = settings.datasource.crypto_key_path
    if not key_path:
        raise ValueError("crypto_key_path 未配置")
    key = Path(key_path).read_bytes()
    return CryptoUtils(key)


def _parse_json_paths(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


class ServerManager:
    """服务器配置查询与凭证解密。所有方法异步、走 AsyncSession。"""

    async def get_server(self, server_code: str) -> PmcpServer:
        async with _db.get_session_factory()() as session:
            stmt = select(PmcpServer).where(
                PmcpServer.server_code == server_code,
                PmcpServer.status == 1,
            )
            result = await session.execute(stmt)
            srv = result.scalar_one_or_none()
            if srv is None:
                from platform_mcp.common.exceptions import SkillError

                raise SkillError(f"服务器 {server_code} 不存在或已禁用")
            return srv

    async def resolve_connection_params(self, server_code: str) -> ServerConnParams:
        srv = await self.get_server(server_code)

        password: str | None = None
        ssh_key_bytes: bytes | None = None
        if srv.encrypted_ssh_key:
            crypto = _get_crypto_utils()
            ssh_key_bytes = crypto.decrypt(srv.encrypted_ssh_key).encode("utf-8")
        elif srv.encrypted_password:
            crypto = _get_crypto_utils()
            password = crypto.decrypt(srv.encrypted_password)

        return ServerConnParams(
            server_code=srv.server_code,
            host=srv.host,
            ssh_port=srv.ssh_port,
            username=srv.username,
            password=password,
            ssh_key_bytes=ssh_key_bytes,
            env_code=srv.env_code,
            max_concurrent=srv.max_concurrent,
            command_timeout=srv.command_timeout,
            allowed_paths=_parse_json_paths(srv.allowed_paths),
            forbidden_paths=_parse_json_paths(srv.forbidden_paths),
        )

    async def list_accessible_servers(self, env_code: str | None = None) -> list[dict[str, Any]]:
        async with _db.get_session_factory()() as session:
            stmt = select(PmcpServer).where(PmcpServer.status == 1)
            if env_code:
                stmt = stmt.where(PmcpServer.env_code == env_code)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "server_code": r.server_code,
                    "server_name": r.server_name,
                    "host": r.host,
                    "ssh_port": r.ssh_port,
                    "username": r.username,
                    "env_code": r.env_code,
                    "status": r.status,
                }
                for r in rows
            ]

    async def test_connection(self, server_code: str) -> dict[str, Any]:
        params = await self.resolve_connection_params(server_code)
        from platform_mcp.skills.server.connection import ssh_connection

        start = time.monotonic()
        try:
            async with ssh_connection(params) as conn:
                # 仅验证连接可用（不执行业务命令）。返回格式与 datasource.test_connection 对齐：
                # {success, message, latency_ms}，前端 ServerPage 显示 "连接成功 (xxx ms)"
                await conn.run(":", check=True, timeout=10)
            latency = int((time.monotonic() - start) * 1000)
            return {"success": True, "message": "连接成功", "latency_ms": latency}
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.warning("server ssh health check failed: {}", e)
            return {"success": False, "message": str(e), "latency_ms": latency}


server_manager = ServerManager()
