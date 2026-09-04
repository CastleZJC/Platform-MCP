"""数据库基础设施 — Base、BaseModel、AsyncSession 工厂、get_db 依赖注入"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from platform_mcp.config import get_settings

__all__ = ["Base", "BaseModel", "get_db"]


class Base(DeclarativeBase):
    pass


class BaseModel(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    inserted_by: Mapped[str | None] = mapped_column(String(64))
    updated_by: Mapped[str | None] = mapped_column(String(64))


def _create_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database.url,
        echo=settings.database.echo,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )


async_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_engine() -> None:
    global async_engine, async_session_factory
    if async_engine is None:
        async_engine = _create_engine()
        async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取已初始化的 session factory（保证非 None，便于 mypy 类型推导）。"""
    _ensure_engine()
    assert async_session_factory is not None
    return async_session_factory


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_and_reset_engine() -> None:
    """释放当前 engine 全部连接并将单例重置为未初始化（跨 event loop 场景专用）。

    MCP 进程在临时事件循环中做启动预热（Skill 停用门 / 配置快照），asyncpg 连接
    绑定创建时的事件循环；loop 关闭后残留连接被主循环复用会触发 asyncpg
    "another operation is in progress"（refresh 每 30s 失败、快照退化初始值）。
    预热完成后调用本函数弃用旧 loop 连接，主循环首次使用时按需重建 engine 与连接池。
    """
    global async_engine, async_session_factory
    if async_engine is not None:
        await async_engine.dispose()
    async_engine = None
    async_session_factory = None
