"""Oracle + MySQL 连接工厂 — ephemeral 连接，asynccontextmanager 管理"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

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


def build_oracle_dsn(params: ConnectionParams) -> str:
    if params.service_name:
        return f"{params.host}:{params.port}/{params.service_name}"
    if params.instance_name:
        return f"{params.host}:{params.port}:{params.instance_name}"
    return f"{params.host}:{params.port}"


def connect_oracle_sync(params: ConnectionParams) -> Any:
    """同步建立 Oracle 连接（thick 模式），供线程池调用。"""
    _ensure_oracle_client()
    import oracledb

    return oracledb.connect(
        user=params.username, password=params.password, dsn=build_oracle_dsn(params)
    )


def interrupt_oracle(conn: Any) -> None:
    """线程安全打断在飞调用（thick OOB break）：超时后先打断再关闭，使服务端
    会话终止而不是继续执行已超时语句。失败仅记录，不抛出。"""
    try:
        conn.break_()
    except Exception as e:
        logger.warning("oracle break_() 打断失败: {}", e)


def close_oracle(conn: Any) -> None:
    """尽力关闭 Oracle 连接（吞异常并记录）。"""
    try:
        conn.close()
    except Exception as e:
        logger.warning("oracle 连接关闭失败: {}", e)


@asynccontextmanager
async def oracle_connection(params: ConnectionParams) -> AsyncIterator[Any]:
    loop = asyncio.get_running_loop()
    conn = await loop.run_in_executor(None, connect_oracle_sync, params)
    try:
        yield conn
    finally:
        await loop.run_in_executor(None, close_oracle, conn)


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
