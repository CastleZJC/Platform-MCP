"""运行时配置中心服务 — pmcp_system_config 动态键 + 30s 短缓存（V3.0 M1，架构 §19.5.2）

已知键注册表：每键标注值类型 / 生效语义（重新登录 or 即时）/ 凭证标记 / i18n 描述。
读取点统一经本服务（30s 短缓存），禁止业务代码直查 pmcp_system_config。
静态引导配置（进程绑定/连接串/路径/权重）仍走 settings.yml 重启生效，不进本中心
（allowed_sql_dirs 属路径类白名单，由各环境 settings.yml 自行设置，不进注册表）。

SMTP 键仅 admin 可改（API 层强制），写操作全量审计留痕；smtp.password 为凭证值：
列表掩码 / 编辑留空重写 / 审计脱敏。无二次确认（2026-09-04 用户决策：装饰性仪式移除）。
"""

from __future__ import annotations

import asyncio
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
    value_type: str  # "string" | "int"
    effect: str  # "relogin" | "immediate"
    sensitive: bool  # 凭证值：不回显（列表掩码/编辑留空重写/审计脱敏）
    desc_key: str  # i18n 字典 key（描述：完整说明）
    default_factory: Callable[[], Any] = field(default=lambda: None)
    label_key: str = ""  # i18n 字典 key（配置项：功能简述，列表首列展示）
    hint_key: str | None = None  # i18n 字典 key（取值参考：单位/范围/枚举，编辑对话框展示）


KNOWN_KEYS: dict[str, ConfigKeySpec] = {
    "sys.default_locale": ConfigKeySpec(
        "sys.default_locale", "string", "relogin", False, "config.desc.sys.default_locale",
        lambda: "zh-CN",
        label_key="config.label.sys.default_locale", hint_key="config.hint.sys.default_locale",
    ),
    "session.timeout_minutes": ConfigKeySpec(
        "session.timeout_minutes", "int", "relogin", False, "config.desc.session.timeout_minutes",
        lambda: 30,
        label_key="config.label.session.timeout_minutes", hint_key="config.hint.session.timeout_minutes",
    ),
    "datasource.default_query_timeout": ConfigKeySpec(
        "datasource.default_query_timeout", "int", "immediate", False,
        "config.desc.datasource.default_query_timeout",
        lambda: _settings().datasource.default_query_timeout,
        label_key="config.label.datasource.default_query_timeout",
        hint_key="config.hint.datasource.default_query_timeout",
    ),
    "datasource.default_max_concurrent": ConfigKeySpec(
        "datasource.default_max_concurrent", "int", "immediate", False,
        "config.desc.datasource.default_max_concurrent",
        lambda: _settings().datasource.default_max_concurrent,
        label_key="config.label.datasource.default_max_concurrent",
        hint_key="config.hint.datasource.default_max_concurrent",
    ),
    "datasource.max_file_size_mb": ConfigKeySpec(
        "datasource.max_file_size_mb", "int", "immediate", False,
        "config.desc.datasource.max_file_size_mb",
        lambda: _settings().datasource.max_file_size_mb,
        label_key="config.label.datasource.max_file_size_mb",
        hint_key="config.hint.datasource.max_file_size_mb",
    ),
    "skill.max_upload_size_mb": ConfigKeySpec(
        "skill.max_upload_size_mb", "int", "immediate", False,
        "config.desc.skill.max_upload_size_mb",
        lambda: _settings().skill.max_upload_size_mb,
        label_key="config.label.skill.max_upload_size_mb",
        hint_key="config.hint.skill.max_upload_size_mb",
    ),
    # smtp.* 捕捉点为 M5 通知模块（aiosmtplib outbox flush 时读取）；注册表先行落位
    "smtp.host": ConfigKeySpec(
        "smtp.host", "string", "immediate", False, "config.desc.smtp.host", lambda: "",
        label_key="config.label.smtp.host", hint_key="config.hint.smtp.host",
    ),
    "smtp.port": ConfigKeySpec(
        "smtp.port", "int", "immediate", False, "config.desc.smtp.port", lambda: 25,
        label_key="config.label.smtp.port", hint_key="config.hint.smtp.port",
    ),
    "smtp.user": ConfigKeySpec(
        "smtp.user", "string", "immediate", False, "config.desc.smtp.user", lambda: "",
        label_key="config.label.smtp.user", hint_key="config.hint.smtp.user",
    ),
    "smtp.password": ConfigKeySpec(
        "smtp.password", "string", "immediate", True, "config.desc.smtp.password", lambda: "",
        label_key="config.label.smtp.password", hint_key="config.hint.smtp.password",
    ),
    "smtp.from": ConfigKeySpec(
        "smtp.from", "string", "immediate", False, "config.desc.smtp.from", lambda: "",
        label_key="config.label.smtp.from", hint_key="config.hint.smtp.from",
    ),
    "log.level": ConfigKeySpec(
        "log.level", "string", "immediate", False, "config.desc.log.level",
        lambda: _settings().log.level,
        label_key="config.label.log.level", hint_key="config.hint.log.level",
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


def validate_registry() -> list[str]:
    """部署期注册表自检：所有配置项参数均需在系统配置注册表中，且默认值可用。

    不允许硬代码兜底：未落库键的当前值即注册表默认值，默认值产出失败或
    类型非法 = 配置链路断裂，部署时直接拒绝启动（main lifespan 调用）。
    检查项（返回问题描述列表，空列表 = 通过）：
    - 每键 default_factory 可产出且不抛异常；
    - int 键默认为非负 int；string 键默认为 str；
    - label_key / hint_key 必须存在于 i18n 资源（配置项简述/取值参考缺失即缺陷）。
    """
    problems: list[str] = []
    for key, spec in KNOWN_KEYS.items():
        try:
            default = spec.default_factory()
        except Exception as e:  # noqa: BLE001 - 部署自检需捕获全部产出异常
            problems.append(f"{key}: 默认值产出失败 {e}")
            continue
        vt = spec.value_type
        if vt == "int":
            if not isinstance(default, int) or isinstance(default, bool) or default < 0:
                problems.append(f"{key}: int 键默认值非法 {default!r}")
        elif not isinstance(default, str):
            problems.append(f"{key}: string 键默认值非法 {default!r}")
        if not spec.label_key or spec.label_key not in _i18n_resources():
            problems.append(f"{key}: 配置项简述 i18n 缺失（label_key={spec.label_key}）")
        if spec.hint_key and spec.hint_key not in _i18n_resources():
            problems.append(f"{key}: 取值参考 i18n 缺失（hint_key={spec.hint_key}）")
    return problems


def _i18n_resources() -> dict:
    """延迟导入 i18n 资源表（避免 runtime_config <-> i18n 循环导入）。"""
    from platform_mcp.i18n import RESOURCES

    return RESOURCES


def _decrypt_if_sensitive(key: str, value: str | None) -> str | None:
    """sensitive 键快照读出时解密（V3.0 M5：smtp.password 等 AES-GCM 加密落库）。

    - 无前缀明文（历史存量值）透传（CryptoUtils.decrypt 语义）；
    - 解密失败（密钥更换等）返回空串并告警：快照不含该键 → get_sync 回退注册表
      默认值，脏配置不阻断业务。
    """
    if value is None:
        return None
    spec = KNOWN_KEYS.get(key)
    if spec is None or not spec.sensitive:
        return value
    try:
        from platform_mcp.datasource.manager import _get_crypto_utils

        return str(_get_crypto_utils().decrypt(value) or "")
    except Exception as e:  # noqa: BLE001 - 解密失败回退默认值，不阻断快照加载
        logger.warning("runtime config key {} decrypt failed, fallback to default: {}", key, e)
        return ""


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
            self._raw = {
                r.config_key: value
                for r in rows
                if (value := _decrypt_if_sensitive(r.config_key, r.config_value)) is not None
            }
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