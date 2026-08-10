"""ConcurrencyLimiter 单元测试 — 信号量按数据源维度控制"""

import asyncio

import pytest

from platform_mcp.mcp_server.skill.concurrency import ConcurrencyLimiter


class TestConcurrencyLimiter:
    def test_get_semaphore_creates_new(self):
        limiter = ConcurrencyLimiter(default_max=3)
        sem = limiter.get_semaphore("ds1")
        assert isinstance(sem, asyncio.Semaphore)

    def test_get_semaphore_returns_same_for_same_ds(self):
        limiter = ConcurrencyLimiter()
        s1 = limiter.get_semaphore("ds1")
        s2 = limiter.get_semaphore("ds1")
        assert s1 is s2

    def test_get_semaphore_custom_max(self):
        limiter = ConcurrencyLimiter(default_max=5)
        sem = limiter.get_semaphore("ds1", max_concurrent=2)
        assert sem._value == 2

    def test_different_datasources_independent(self):
        limiter = ConcurrencyLimiter()
        s1 = limiter.get_semaphore("ds1")
        s2 = limiter.get_semaphore("ds2")
        assert s1 is not s2

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        limiter = ConcurrencyLimiter(default_max=2)
        async with limiter.acquire("ds1"):
            pass
        sem = limiter.get_semaphore("ds1")
        assert sem._value == 2
