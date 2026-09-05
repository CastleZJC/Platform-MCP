"""outbox 周期 flush 任务（V3.0 M5，计划 5.2）

仅 Web 进程启动（``main.py`` lifespan）：outbox 单写多读——MCP 进程捕捉点只写
``pmcp_notify_outbox``，Web 进程统一发送，避免多进程重复投递（部署原则 #5 无
fire-and-forget；架构 §19.5.5 outbox 模式）。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from platform_mcp.config import get_settings


async def start_outbox_flush(interval: float | None = None) -> asyncio.Task:
    """启动周期 flush 后台任务（Web lifespan 调用，随进程生命周期 cancel）。"""
    if interval is None:
        interval = float(get_settings().notify.flush_interval_seconds)

    async def _loop() -> None:
        from platform_mcp.notify.sender import flush_outbox

        while True:
            try:
                result = await flush_outbox()
                if result["sent"] or result["failed"]:
                    logger.info(
                        "notify outbox flush: sent={} failed={} pending={}",
                        result["sent"], result["failed"], result["pending"],
                    )
            except Exception as e:  # noqa: BLE001 - 周期任务任何故障不终止循环
                logger.warning("notify outbox flush loop error (non-fatal): {}", e)
            await asyncio.sleep(interval)

    return asyncio.create_task(_loop())
