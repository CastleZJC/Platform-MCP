"""SMTP 发送器与 outbox flush（V3.0 M5，架构 §19.5.5 / 计划 5.2）

- SMTP 连接参数经运行时配置中心 ``smtp.*`` 键（flush 时实时读取，免改配置重启）；
  ``smtp.password`` 为 sensitive 键：落库 AES-GCM 加密、快照读出时解密（写入/读取
  透明加解密改造见 ``api/system_config.py`` / ``common/runtime_config.py``）。
- :func:`flush_outbox` —— 取 ``pending`` + 未超限 ``failed`` 逐条发送并回写状态；
  SMTP 未配置（host 空）时保持 pending 堆积待发（部署前置依赖，R-13），不报错。
- 单条发送失败：``retry_count+1``、``status=failed``、``error_message`` 留痕（F-38
  可重试可审计）；达到 ``max_retry`` 后不再重试（状态留 failed，管理页可见）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from platform_mcp.config import get_settings

# 发送超时（连接 + 交互整体上限；SMTP 服务器慢速时避免拖垮 flush 周期）
_SMTP_TIMEOUT_SECONDS = 15


async def get_smtp_config() -> dict[str, Any] | None:
    """读运行时配置中心 smtp.*（flush 时实时读取）。

    返回 ``{"host", "port", "user", "password", "from"}``；``host`` 为空（未配置）返回
    ``None`` —— 生产 SMTP 参数为部署前置依赖（R-13），未配置时 outbox 保持 pending。
    """
    from platform_mcp.common.runtime_config import runtime_config

    host = str(await runtime_config.get("smtp.host") or "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(await runtime_config.get("smtp.port") or 25),
        "user": str(await runtime_config.get("smtp.user") or ""),
        "password": str(await runtime_config.get("smtp.password") or ""),
        "from": str(await runtime_config.get("smtp.from") or "").strip(),
    }


async def send_via_smtp(recipient: str, subject: str, body: str, smtp: dict[str, Any]) -> None:
    """aiosmtplib 单条发送（同步语义：失败抛异常由调用方记 outbox failed）。"""
    from email.message import EmailMessage

    import aiosmtplib

    message = EmailMessage()
    message["From"] = smtp["from"] or smtp["user"] or "platform-mcp@localhost"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=smtp["host"],
        port=smtp["port"],
        username=smtp["user"] or None,
        password=smtp["password"] or None,
        timeout=_SMTP_TIMEOUT_SECONDS,
    )


async def flush_outbox() -> dict[str, int]:
    """发送一轮 outbox：pending + failed(retry_count < max_retry)，上限 flush_batch_size。

    返回 ``{"sent": n, "failed": n, "pending": m}``（pending=本轮因 SMTP 未配置跳过的条数）。
    """
    from platform_mcp.common.database import get_session_factory
    from platform_mcp.notify.models import PmcpNotifyOutbox

    settings = get_settings()
    sent = failed = skipped = 0
    smtp = await get_smtp_config()
    if smtp is None:
        # 未配置 SMTP：不取件不报错（保持 pending 堆积待发，R-13）；仅统计积压量
        async with get_session_factory()() as session:
            pending = (
                await session.execute(
                    select(PmcpNotifyOutbox.id).where(
                        PmcpNotifyOutbox.status == "pending",
                        PmcpNotifyOutbox.retry_count < settings.notify.max_retry,
                    )
                )
            ).all()
        if pending:
            logger.info("notify outbox: SMTP 未配置，{} 条待发堆积（配置见系统配置页 smtp.*）", len(pending))
        return {"sent": 0, "failed": 0, "pending": len(pending)}

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(PmcpNotifyOutbox)
                    .where(
                        PmcpNotifyOutbox.status.in_(["pending", "failed"]),
                        PmcpNotifyOutbox.retry_count < settings.notify.max_retry,
                    )
                    .order_by(PmcpNotifyOutbox.id)
                    .limit(settings.notify.flush_batch_size)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            try:
                await send_via_smtp(row.recipient, row.subject, row.body, smtp)
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc)
                row.error_message = None
                sent += 1
            except Exception as e:  # noqa: BLE001 - 单条失败继续本轮其余条目
                row.status = "failed"
                row.retry_count += 1
                row.error_message = str(e)[:2000]
                failed += 1
                logger.warning(
                    "notify outbox send failed (id={} retry={}): {}", row.id, row.retry_count, e
                )
        await session.commit()
    return {"sent": sent, "failed": failed, "pending": skipped}
