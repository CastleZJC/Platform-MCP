"""基础并发限流 — asyncio.Semaphore 按数据源维度控制"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class ConcurrencyLimiter:
    """按 datasource_code 维护独立的 Semaphore 限流器。"""

    def __init__(self, default_max: int = 5):
        self._default_max = default_max
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def get_semaphore(self, datasource_code: str, max_concurrent: int | None = None) -> asyncio.Semaphore:
        max_val = max_concurrent or self._default_max
        if datasource_code not in self._semaphores:
            self._semaphores[datasource_code] = asyncio.Semaphore(max_val)
        return self._semaphores[datasource_code]

    @asynccontextmanager
    async def acquire(self, datasource_code: str, max_concurrent: int | None = None) -> AsyncIterator[None]:
        sem = self.get_semaphore(datasource_code, max_concurrent)
        await sem.acquire()
        try:
            yield
        finally:
            sem.release()
