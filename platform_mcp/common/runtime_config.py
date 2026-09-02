"""运行时配置中心服务 — pmcp_system_config 动态键 + 30s 短缓存（V3.0 M1，架构 §19.5.2）

已知键注册表：每键标注值类型 / 生效语义（重新登录 or 即时）/ 安全级别 / i18n 描述。
读取点统一经本服务（30s 短缓存），禁止业务代码直查 pmcp_system_config。
静态引导配置（进程绑定/连接串/路径/权重）仍走 settings.yml 重启生效，不进本中心。

安全敏感键（allowed_sql_dirs / allowed_envs / smtp.*）：仅 admin 可改（API 层强制），
修改强制审计 + 二次确认（confirm_sensitive）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

CACHE_TTL_SECONDS = 30

_LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")


def _settings() -> Any:
    from platform_mcp.config import get_settings

    return get_settings()


@dataclass(frozen=True)
class ConfigKeySpec:
    """已知运行时配置键的注册表条目。"""

    key: str
    value_type: str  # "string" | "int" | "json_list" | "json_list_or_null"
    effect: str  # "relogin" | "immediate"
    sensitive: bool
    desc_key: str  # i18n 字典 key
    default_factory: Callable[[], Any] = field(default=lambda: None)


KNOWN_KEYS: dict[str, ConfigKeySpec] = {
    "sys.default_locale": ConfigKeySpec(
        "sys.default_locale", "string", "relogin", False, "config.desc.sys.default_locale",
        lambda: "zh-CN",
    ),
    "session.timeout_minutes": ConfigKeySpec(
        "session.timeout_minutes", "int", "relogin", False, "config.desc.session.timeout_minutes",
        lambda: 30,
    ),
    "datasource.default_query_timeout": ConfigKeySpec(
        "datasource.default_query_timeout", "int", "immediate", False,
        "config.desc.datasource.default_query_timeout",
        lambda: _settings().datasource.default_query_timeout,
    ),
    "datasource.default_max_concurrent": ConfigKeySpec(
        "datasource.default_max_concurrent", "int", "immediate", False,
        "config.desc.datasource.default_max_concurrent",
        lambda: _settings().datasource.default_max_concurrent,
    ),
    "datasource.max_file_size_mb": ConfigKeySpec(
        "datasource.max_file_size_mb", "int", "immediate", False,
        "config.desc.datasource.max_file_size_mb",
        lambda: _settings().datasource.max_file_size_mb,
    ),
    "datasource.allowed_sql_dirs": ConfigKeySpec(
        "datasource.allowed_sql_dirs", "json_list", "immediate", True,
        "config.desc.datasource.allowed_sql_dirs",
        lambda: _settings().datasource.allowed_sql_dirs,
    ),
    "skill.max_upload_size_mb": ConfigKeySpec(
        "skill.max_upload_size_mb", "int", "immediate", False,
        "config.desc.skill.max_upload_size_mb",
        lambda: _settings().skill.max_upload_size_mb,
    ),
    "mcp.allowed_envs": ConfigKeySpec(
        "mcp.allowed_envs", "json_list_or_null", "immediate", True,
        "config.desc.mcp.allowed_envs",
        lambda: _settings().mcp.allowed_envs,
    ),
    # smtp.* 捕捉点为 M5 通知模块（aiosmtplib outbox flush 时读取）；注册表先行落位
    "smtp.host": ConfigKeySpec("smtp.host", "string", "immediate", True, "config.desc.smtp.host", lambda: ""),
    "smtp.port": ConfigKeySpec("smtp.port", "int", "immediate", True, "config.desc.smtp.port", lambda: 25),
    "smtp.user": ConfigKeySpec("smtp.user", "string", "immediate", True, "config.desc.smtp.user", lambda: ""),
    "smtp.password": ConfigKeySpec(
        "smtp.password", "string", "immediate", True, "config.desc.smtp.password", lambda: ""
    ),
    "smtp.from": ConfigKeySpec("smtp.from", "string", "immediate", True, "config.desc.smtp.from", lambda: ""),
    "log.level": ConfigKeySpec(
        "log.level", "string", "immediate", False, "config.desc.log.level",
        lambda: _settings().log.level,
    ),
}


def validate_value(key: str, raw: str) -> Any:
    """按注册表类型解析并校验已知键的值；未知键原样返回字符串。

    抛出 ValueError 表示值不合法（API 层转 16004）。
    """
    spec = KNOWN_KEYS.get(key)
    if spec is None:
        return raw
    if spec.value_type == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"键 {key} 需要 int 类型值")
        if value < 0:
            raise ValueError(f"键 {key} 不允许负数")
        return value
    if spec.value_type == "json_list":
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise ValueError(f"键 {key} 需要合法 JSON 数组")
        if not isinstance(parsed, list) or not all(isinstance(i, str) for i in parsed):
            raise ValueError(f"键 {key} 需要字符串数组 JSON")
        return parsed
    if spec.value_type == "json_list_or_null":
        if raw.strip().lower() in ("null", "none", ""):
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise ValueError(f"键 {key} 需要合法 JSON 数组或 null")
        if not isinstance(parsed, list) or not all(isinstance(i, str) for i in parsed):
            raise ValueError(f"键 {key} 需要字符串数组 JSON 或 null")
        return parsed
    # string
    if key == "sys.default_locale":
        from platform_mcp.i18n import SUPPORTED_LOCALES

        if raw not in SUPPORTED_LOCALES:
            raise ValueError(f"键 {key} 仅支持 {'/'.join(SUPPORTED_LOCALES)}")
        return raw
    if key == "log.level":
        if raw.upper() not in _LOG_LEVELS:
            raise ValueError(f"键 {key} 仅支持 {'/'.join(_LOG_LEVELS)}")
        return raw.upper()
    return raw


class RuntimeConfigService:
    """运行时配置读取服务：30s 快照缓存 + 失效刷新 + log.level 即时应用。"""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._raw: dict[str, str] = {}
        self._snapshot_at: float = 0.0
        self._loaded = False
        self._applied_log_level: str | None = None
        self._refreshing = False

    async def refresh(self, force: bool = False) -> None:
        """从 pmcp_system_config 加载启用键快照（未过期时 no-op）。

        DB 不可用时保留旧快照；首次加载失败回退注册表默认值。
        """
        if not force and self._loaded and time.monotonic() - self._snapshot_at < self._ttl:
            return
        if self._refreshing:
            return
        self._refreshing = True
        try:
            from sqlalchemy import select

            from platform_mcp.common.database import get_session_factory
            from platform_mcp.common.models import PmcpSystemConfig

            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    select(PmcpSystemConfig).where(PmcpSystemConfig.status == 1)
                )
                rows = result.scalars().all()
            self._raw = {r.config_key: r.config_value for r in rows if r.config_value is not None}
            self._snapshot_at = time.monotonic()
            self._loaded = True
            self._apply_log_level()
        except Exception as e:
            if not self._loaded:
                self._raw = {}
                self._loaded = True
                self._snapshot_at = time.monotonic()
            logger.warning("runtime config refresh failed, keep previous snapshot: {}", e)
        finally:
            self._refreshing = False

    def invalidate(self) -> None:
        """配置变更后失效缓存（下一次读取/后台刷新即拉新值）。"""
        self._snapshot_at = 0.0

    async def get(self, key: str) -> Any:
        """异步取已知键的类型化当前值（过期自动刷新）。"""
        await self.refresh()
        return self.get_sync(key)

    def get_sync(self, key: str) -> Any:
        """同步取已知键的类型化当前值。

        - 无新鲜快照时回退注册表默认值（settings 口径），并尝试调度异步刷新
          （有运行中的事件循环时 fire-and-forget，无循环时静默回退默认值）；
        - 快照值解析失败回退默认值并告警（脏配置不阻断业务）。
        """
        spec = KNOWN_KEYS.get(key)
        if spec is None:
            raise KeyError(f"未知运行时配置键: {key}")
        raw = self._raw.get(key)
        if raw is not None:
            try:
                return validate_value(key, raw)
            except ValueError as e:
                logger.warning("runtime config key {} has invalid value {!r}, fallback to default: {}",
                               key, raw, e)
        self._schedule_refresh()
        return spec.default_factory()

    def raw_configured(self, key: str) -> str | None:
        """已知键的原始配置值（未配置返回 None）；供注册表 API 展示"已配置/默认"。"""
        return self._raw.get(key)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def _schedule_refresh(self) -> None:
        """在异步上下文中调度一次缓存刷新（no-op 守卫防抖）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.refresh())

    def _apply_log_level(self) -> None:
        level = self.get_sync("log.level")
        if not isinstance(level, str) or level == self._applied_log_level:
            return
        from platform_mcp.common.logsetup import apply_log_level

        apply_log_level(level)
        self._applied_log_level = level
        logger.debug("log.level applied: {}", level)


runtime_config = RuntimeConfigService()


async def start_background_refresh(interval: float = CACHE_TTL_SECONDS) -> asyncio.Task:
    """启动周期刷新后台任务（Web lifespan / MCP streamable-http lifespan 调用）。

    覆盖进程空闲期 log.level 等即时键的应用（无请求时 get_sync 不触发刷新）。
    """
    async def _loop() -> None:
        while True:
            await runtime_config.refresh(force=True)
            await asyncio.sleep(interval)

    return asyncio.create_task(_loop())