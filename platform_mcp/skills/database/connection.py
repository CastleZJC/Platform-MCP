"""Oracle + MySQL 连接工厂 — ephemeral 连接，asynccontextmanager 管理"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from platform_mcp.datasource.manager import ConnectionParams

_oracle_initialized = False


def _ensure_oracle_client() -> None:
    global _oracle_initialized
    if _oracle_initialized:
        return
    from platform_mcp.config import get_settings

    settings = get_settings()
    lib_dir = settings.datasource.oracle_instant_client_dir
    if not lib_dir:
        raise ValueError("oracle_instant_client_dir 未配置")
    import oracledb

    oracledb.init_oracle_client(lib_dir=lib_dir)
    _oracle_initialized = True
    logger.info("Oracle thick mode initialized: {}", lib_dir)


@asynccontextmanager
async def oracle_connection(params: ConnectionParams) -> AsyncIterator:
    _ensure_oracle_client()
    import oracledb

    if params.service_name:
        dsn = f"{params.host}:{params.port}/{params.service_name}"
    elif params.instance_name:
        dsn = f"{params.host}:{params.port}:{params.instance_name}"
    else:
        dsn = f"{params.host}:{params.port}"

    loop = asyncio.get_running_loop()
    conn = await loop.run_in_executor(
        None,
        lambda: oracledb.connect(user=params.username, password=params.password, dsn=dsn),
    )
    try:
        yield conn
    finally:
        try:
            await loop.run_in_executor(None, conn.close)
        except Exception:
            pass


@asynccontextmanager
async def mysql_connection(params: ConnectionParams) -> AsyncIterator:
    import aiomysql

    conn = await aiomysql.connect(
        host=params.host,
        port=params.port,
        user=params.username,
        password=params.password,
        db=params.database or None,
        charset="utf8mb4",
        connect_timeout=30,
    )
    try:
        yield conn
    finally:
        try:
            conn.close()
            await conn.ensure_closed()
        except Exception:
            pass


@asynccontextmanager
async def get_connection(params: ConnectionParams) -> AsyncIterator:
    if params.db_type == "oracle":
        async with oracle_connection(params) as conn:
            yield conn
    elif params.db_type == "mysql":
        async with mysql_connection(params) as conn:
            yield conn
    else:
        raise ValueError(f"不支持的数据库类型: {params.db_type}")
