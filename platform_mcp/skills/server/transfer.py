"""SFTP 中转目录管理 — exchange 目录解析、transfer_id 隔离、完成/失败清理 + TTL 兜底

BUG20260814163941（BUG-3/5）：工作站↔MCP 服务器文件中转统一存储于
settings.datasource.sftp_exchange_dir（默认 {项目根}/sftp_exchange），
每次传输任务独立 transfer_id（uuid v4）目录，物理隔离多人同名文件。

防误删铁律：
1. 删除目标必须严格匹配 {exchange_dir}/{uuid4} 两段结构
2. transfer_id 必须通过 uuid v4 正则校验，拒绝路径穿越
3. 删除实现用 pathlib + shutil.rmtree，禁止拼接 shell rm
4. 删除前 resolve() 校验最终路径仍在 exchange_dir 之下
5. 永不触碰 exchange 根目录本身及其他 transfer_id 目录
"""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from pathlib import Path

from loguru import logger

TRANSFER_TTL_SECONDS = 1800  # 下载中转 TTL：CC 未显式 DELETE 时 30 分钟兜底清理

_TRANSFER_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

_exchange_dir_cache: Path | None = None


def get_exchange_dir() -> Path:
    """解析中转目录并确保存在（权限 0700）。结果进程内缓存。"""
    global _exchange_dir_cache
    if _exchange_dir_cache is not None:
        return _exchange_dir_cache
    from platform_mcp.config import get_settings

    configured = get_settings().datasource.sftp_exchange_dir
    if configured:
        base = Path(configured).resolve()
    else:
        base = Path(__file__).resolve().parent.parent.parent.parent / "sftp_exchange"
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError:
        logger.warning("无法设置中转目录权限 0700: {}", base)
    _exchange_dir_cache = base
    return base


def reset_exchange_dir_cache() -> None:
    """测试辅助：清空目录缓存以便切换配置。"""
    global _exchange_dir_cache
    _exchange_dir_cache = None


def new_transfer_id() -> str:
    return str(uuid.uuid4())


def is_valid_transfer_id(transfer_id: str) -> bool:
    return bool(_TRANSFER_ID_PATTERN.fullmatch(transfer_id or ""))


def is_safe_filename(filename: str) -> bool:
    if not filename or len(filename) > 255:
        return False
    if "/" in filename or "\\" in filename or "\x00" in filename:
        return False
    return filename not in (".", "..")


def stage_path(transfer_id: str, filename: str) -> Path:
    """校验并返回 {exchange}/{transfer_id}/{filename}；非法输入抛 PathSecurityError。"""
    from platform_mcp.common.exceptions import PathSecurityError

    if not is_valid_transfer_id(transfer_id):
        raise PathSecurityError(f"非法 transfer_id: {transfer_id!r}")
    if not is_safe_filename(filename):
        raise PathSecurityError(f"非法中转文件名: {filename!r}")
    exchange = get_exchange_dir().resolve()
    target = (exchange / transfer_id / filename).resolve()
    if target.parent.parent != exchange:
        raise PathSecurityError(f"中转路径越界: {transfer_id}/{filename}")
    return target


def cleanup_transfer(transfer_id: str) -> bool:
    """删除 {exchange}/{transfer_id}/ 整个任务目录；目录不存在返回 False。"""
    if not is_valid_transfer_id(transfer_id):
        return False
    exchange = get_exchange_dir().resolve()
    target = (exchange / transfer_id).resolve()
    if target.parent != exchange:
        return False
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def staged_transfer_id(local_path: str | Path) -> str | None:
    """若 local_path 形如 {exchange}/{uuid4}/<file>，返回 transfer_id，否则 None。"""
    try:
        p = Path(local_path).resolve()
        exchange = get_exchange_dir().resolve()
        if p.parent.parent == exchange and is_valid_transfer_id(p.parent.name):
            return p.parent.name
    except OSError:
        pass
    return None


def maybe_cleanup_staged(local_path: str | Path) -> None:
    """上传完成/失败后自动清理对应中转任务目录（仅限自身 transfer_id）。"""
    tid = staged_transfer_id(local_path)
    if not tid:
        return
    try:
        cleanup_transfer(tid)
    except OSError:
        logger.warning("中转目录清理失败: transfer_id={}", tid)


def cleanup_expired_transfers() -> int:
    """TTL 兜底清理：删除超时未被取回的中转目录，返回清理数量。"""
    exchange = get_exchange_dir().resolve()
    now = time.time()
    removed = 0
    try:
        entries = list(exchange.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or not is_valid_transfer_id(entry.name):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime > TRANSFER_TTL_SECONDS:
            try:
                shutil.rmtree(entry)
                removed += 1
                logger.info("TTL 清理过期中转目录: {}", entry.name)
            except OSError:
                logger.warning("TTL 清理失败: {}", entry.name)
    return removed
