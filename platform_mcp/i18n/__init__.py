"""i18n 资源字典 — key → locale 文案（V3.0 M1，架构 §19.5.2）

扩展性约束：新增语言 = 加字典条目 + SUPPORTED_LOCALES 枚举，禁止任何硬编码语言分支。
消费方：系统配置注册表描述/生效语义标签（GET /system-config/registry 按 locale 返回）；
后续里程碑的动态产物（README/审核报告/搜索结果）按同一字典扩展。
"""

from __future__ import annotations

from typing import Any

DEFAULT_LOCALE = "zh-CN"
SUPPORTED_LOCALES: tuple[str, ...] = ("zh-CN", "en-US")

RESOURCES: dict[str, dict[str, str]] = {
    # ==== 运行时配置中心：已知键描述 ====
    "config.desc.sys.default_locale": {
        "zh-CN": "系统默认界面语言；用户未设置个人语言偏好时登录回退使用",
        "en-US": "System default UI language; fallback at login when user preference is unset",
    },
    "config.desc.session.timeout_minutes": {
        "zh-CN": "Web 会话空闲超时（分钟）；登录时快照，重新登录后生效",
        "en-US": "Web session idle timeout (minutes); snapshotted at login, effective after re-login",
    },
    "config.desc.datasource.default_query_timeout": {
        "zh-CN": "数据源查询默认超时（秒）；数据源未单独配置时使用",
        "en-US": "Default query timeout (seconds) when datasource has no own value",
    },
    "config.desc.datasource.default_max_concurrent": {
        "zh-CN": "数据源默认最大并发数；数据源未单独配置时使用",
        "en-US": "Default max concurrent connections when datasource has no own value",
    },
    "config.desc.datasource.max_file_size_mb": {
        "zh-CN": "SQL 文件大小上限（MB），超限拒绝执行",
        "en-US": "Max SQL file size (MB); larger files are rejected",
    },
    "config.desc.datasource.allowed_sql_dirs": {
        "zh-CN": "SQL 文件与本地传输路径白名单（JSON 数组）；PROD 目标强制要求配置",
        "en-US": "Allowed SQL file / local transfer path whitelist (JSON array); required for PROD targets",
    },
    "config.desc.skill.max_upload_size_mb": {
        "zh-CN": "Skill 包上传大小上限（MB）",
        "en-US": "Max Skill package upload size (MB)",
    },
    "config.desc.mcp.allowed_envs": {
        "zh-CN": "MCP 可访问环境白名单（JSON 数组或 null=不限）；与角色环境限制叠加生效",
        "en-US": "MCP accessible env whitelist (JSON array or null=unrestricted); stacks with role checks",
    },
    "config.desc.smtp.host": {
        "zh-CN": "SMTP 服务器地址（邮件提醒，M5 通知模块上线后消费）",
        "en-US": "SMTP server host (email alerts; consumed by notify module from M5)",
    },
    "config.desc.smtp.port": {
        "zh-CN": "SMTP 服务器端口（M5 生效）",
        "en-US": "SMTP server port (effective from M5)",
    },
    "config.desc.smtp.user": {
        "zh-CN": "SMTP 认证用户名（M5 生效）",
        "en-US": "SMTP auth username (effective from M5)",
    },
    "config.desc.smtp.password": {
        "zh-CN": "SMTP 认证密码（AES-GCM 加密存储，M5 生效）",
        "en-US": "SMTP auth password (AES-GCM encrypted; effective from M5)",
    },
    "config.desc.smtp.from": {
        "zh-CN": "发件人地址（M5 生效）",
        "en-US": "From address (effective from M5)",
    },
    "config.desc.log.level": {
        "zh-CN": "应用日志级别（TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL），修改后即时生效",
        "en-US": "Application log level (TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL); effective immediately",
    },
    # ==== 生效语义标签 ====
    "config.effect.relogin": {
        "zh-CN": "重新登录后生效",
        "en-US": "Effective after re-login",
    },
    "config.effect.immediate": {
        "zh-CN": "即时生效",
        "en-US": "Effective immediately",
    },
}


def normalize_locale(locale: str | None) -> str:
    """校验 locale 合法性，非法或空回退默认语言。"""
    if locale in SUPPORTED_LOCALES:
        return locale
    return DEFAULT_LOCALE


def get_text(key: str, locale: str | None = None, **params: Any) -> str:
    """按 locale 取字典文案；缺语言回退默认语言，缺 key 回退 key 本身。

    params 为 str.format 命名参数。
    """
    entry = RESOURCES.get(key)
    if not entry:
        return key
    text = entry.get(normalize_locale(locale)) or entry.get(DEFAULT_LOCALE)
    if text is None:
        return key
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
    return text