"""数据源连接管理器 — 查询配置、解密密码、健康检查"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select

from platform_mcp.common import database as _db
from platform_mcp.datasource.models import PmcpDatasource


@dataclass
class ConnectionParams:
    db_type: str
    host: str
    port: int
    username: str
    password: str
    instance_name: str | None = None
    service_name: str | None = None
    database: str | None = None
    query_timeout: int = 300
    max_concurrent: int = 5
    env_code: str = "DEV"
    datasource_code: str = ""


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


class DatasourceManager:

    async def get_datasource(self, datasource_code: str) -> PmcpDatasource:
        async with _db.get_session_factory()() as session:
            stmt = select(PmcpDatasource).where(
                PmcpDatasource.datasource_code == datasource_code,
                PmcpDatasource.status == 1,
            )
            result = await session.execute(stmt)
            ds = result.scalar_one_or_none()
            if ds is None:
                from platform_mcp.common.exceptions import DataSourceError

                raise DataSourceError(f"数据源 {datasource_code} 不存在或已禁用")
            return ds

    async def resolve_connection_params(self, datasource_code: str) -> ConnectionParams:
        from platform_mcp.config import get_settings

        ds = await self.get_datasource(datasource_code)
        password = ""
        if ds.encrypted_password:
            crypto = _get_crypto_utils()
            password = crypto.decrypt(ds.encrypted_password)

        settings = get_settings()
        return ConnectionParams(
            db_type=ds.db_type,
            host=ds.host,
            port=ds.port,
            username=ds.username,
            password=password,
            instance_name=ds.instance_name,
            service_name=ds.service_name,
            database=ds.database,
            query_timeout=ds.query_timeout or settings.datasource.default_query_timeout,
            max_concurrent=ds.max_concurrent or settings.datasource.default_max_concurrent,
            env_code=ds.env_code,
            datasource_code=ds.datasource_code,
        )

    async def list_accessible_datasources(self, env_code: str | None = None) -> list[dict[str, Any]]:
        async with _db.get_session_factory()() as session:
            stmt = select(PmcpDatasource).where(PmcpDatasource.status == 1)
            if env_code:
                stmt = stmt.where(PmcpDatasource.env_code == env_code)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "datasource_code": r.datasource_code,
                    "datasource_name": r.datasource_name,
                    "db_type": r.db_type,
                    "host": r.host,
                    "port": r.port,
                    "env_code": r.env_code,
                    "status": r.status,
                }
                for r in rows
            ]

    async def test_connection(self, datasource_code: str) -> dict[str, Any]:
        params = await self.resolve_connection_params(datasource_code)
        from platform_mcp.skills.database.connection import get_connection

        start = time.monotonic()
        try:
            async with get_connection(params) as conn:
                check_sql = "SELECT 1 FROM DUAL" if params.db_type == "oracle" else "SELECT 1"
                if params.db_type == "oracle":
                    import asyncio

                    loop = asyncio.get_running_loop()
                    cursor = conn.cursor()
                    await loop.run_in_executor(None, lambda: cursor.execute(check_sql))
                    cursor.close()
                else:
                    async with conn.cursor() as cur:
                        await cur.execute(check_sql)
                        await cur.fetchone()

            latency = int((time.monotonic() - start) * 1000)
            return {"success": True, "message": "连接成功", "latency_ms": latency}
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.warning("datasource health check failed: {}", e)
            return {"success": False, "message": str(e), "latency_ms": latency}


datasource_manager = DatasourceManager()
