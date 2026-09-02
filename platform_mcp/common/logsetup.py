"""共享日志初始化 — loguru sink 参数存档 + 日志级别运行时热切换（V3.0 M1，架构 §19.5.2）

Web 与 MCP 双入口统一入口；apply_log_level 由 runtime_config 在 log.level 变更时回调（即时生效，
不重启进程）。无 sink 时静默记录级别（setup_logging 随后以该级别初始化）。
"""

from __future__ import annotations

import sys
from typing import Any

from loguru import logger

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

_current_level: str = "INFO"
_sink_params: list[dict[str, Any]] = []


def setup_logging(settings: Any, file_prefix: str = "Platform-MCP") -> None:
    """按 settings.log 初始化 loguru sinks。

    file_prefix 区分入口日志文件（Web: Platform-MCP-*.log / MCP: Platform-MCP-mcp-*.log）。
    若 setup 前已有 apply_log_level 记录的级别，以该级别为准（启动早期热切换不丢）。
    """
    global _current_level, _sink_params

    level = _current_level if not _sink_params and _current_level != "INFO" else settings.log.level
    stderr_params: dict[str, Any] = {"sink": sys.stderr, "level": level, "format": _LOG_FORMAT}
    params = [stderr_params]
    log_dir = settings.log.dir
    if log_dir:
        # 延迟 import 保持可 patch 性（模块级绑定会在 patch pathlib.Path 时绕过 mock）
        from pathlib import Path

        Path(log_dir).mkdir(exist_ok=True)
        params.append(
            {
                "sink": f"{log_dir}/{file_prefix}-{{time:YYYY-MM-DD}}.log",
                "level": level,
                "rotation": settings.log.rotation,
                "retention": settings.log.retention,
                "encoding": "utf-8",
            }
        )
    _current_level = level
    _sink_params = params
    logger.remove()
    for p in params:
        logger.add(**p)


def apply_log_level(level: str) -> None:
    """热切换日志级别：移除全部 sink 后按原参数（除 level）重建。

    setup 前调用时仅记录级别，由随后的 setup_logging 采纳。
    """
    global _current_level, _sink_params

    level = level.upper()
    if level == _current_level:
        return
    if not _sink_params:
        _current_level = level
        return
    _current_level = level
    rebuilt_params = []
    logger.remove()
    for p in _sink_params:
        rebuilt = {**p, "level": level}
        logger.add(**rebuilt)
        rebuilt_params.append(rebuilt)
    _sink_params = rebuilt_params