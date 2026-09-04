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
    # ==== 运行时配置中心：配置项功能简述（列表“配置项”列）====
    "config.label.sys.default_locale": {
        "zh-CN": "系统默认界面语言",
        "en-US": "System default UI language",
    },
    "config.label.session.timeout_minutes": {
        "zh-CN": "Web 会话超时",
        "en-US": "Web session timeout",
    },
    "config.label.datasource.default_query_timeout": {
        "zh-CN": "查询默认超时",
        "en-US": "Default query timeout",
    },
    "config.label.datasource.default_max_concurrent": {
        "zh-CN": "数据源默认并发上限",
        "en-US": "Default datasource concurrency",
    },
    "config.label.datasource.max_file_size_mb": {
        "zh-CN": "SQL 文件大小上限",
        "en-US": "SQL file size limit",
    },
    "config.label.datasource.allowed_sql_dirs": {
        "zh-CN": "SQL 文件路径白名单",
        "en-US": "SQL file path whitelist",
    },
    "config.label.skill.max_upload_size_mb": {
        "zh-CN": "Skill 上传大小上限",
        "en-US": "Skill upload size limit",
    },
    "config.label.mcp.allowed_envs": {
        "zh-CN": "MCP 可访问环境白名单",
        "en-US": "MCP accessible env whitelist",
    },
    "config.label.smtp.host": {
        "zh-CN": "SMTP 服务器地址",
        "en-US": "SMTP server host",
    },
    "config.label.smtp.port": {
        "zh-CN": "SMTP 端口",
        "en-US": "SMTP port",
    },
    "config.label.smtp.user": {
        "zh-CN": "SMTP 认证用户",
        "en-US": "SMTP auth user",
    },
    "config.label.smtp.password": {
        "zh-CN": "SMTP 认证密码",
        "en-US": "SMTP auth password",
    },
    "config.label.smtp.from": {
        "zh-CN": "邮件发件人",
        "en-US": "Email sender address",
    },
    "config.label.log.level": {
        "zh-CN": "应用日志级别",
        "en-US": "Application log level",
    },
    # ==== 运行时配置中心：取值参考（单位/范围/枚举，编辑对话框展示）====
    "config.hint.sys.default_locale": {
        "zh-CN": "可选值：zh-CN / en-US",
        "en-US": "Allowed: zh-CN / en-US",
    },
    "config.hint.session.timeout_minutes": {
        "zh-CN": "范围 1-1440，单位分钟",
        "en-US": "Range 1-1440, in minutes",
    },
    "config.hint.datasource.default_query_timeout": {
        "zh-CN": "范围 1-86400，单位秒",
        "en-US": "Range 1-86400, in seconds",
    },
    "config.hint.datasource.default_max_concurrent": {
        "zh-CN": "范围 1-100",
        "en-US": "Range 1-100",
    },
    "config.hint.datasource.max_file_size_mb": {
        "zh-CN": "范围 1-1024，单位 MB",
        "en-US": "Range 1-1024, in MB",
    },
    "config.hint.datasource.allowed_sql_dirs": {
        "zh-CN": "JSON 字符串数组，例：[\"/tmp\"]",
        "en-US": "JSON string array, e.g. [\"/tmp\"]",
    },
    "config.hint.skill.max_upload_size_mb": {
        "zh-CN": "范围 1-2048，单位 MB",
        "en-US": "Range 1-2048, in MB",
    },
    "config.hint.mcp.allowed_envs": {
        "zh-CN": "JSON 字符串数组或 null（null=不限），例：[\"DEV\",\"UAT\"]",
        "en-US": "JSON string array or null (null=unrestricted), e.g. [\"DEV\",\"UAT\"]",
    },
    "config.hint.smtp.host": {
        "zh-CN": "字符串，例：smtp.example.com",
        "en-US": "String, e.g. smtp.example.com",
    },
    "config.hint.smtp.port": {
        "zh-CN": "范围 1-65535",
        "en-US": "Range 1-65535",
    },
    "config.hint.smtp.user": {
        "zh-CN": "字符串",
        "en-US": "String",
    },
    "config.hint.smtp.password": {
        "zh-CN": "字符串，入库 AES-GCM 加密",
        "en-US": "String, AES-GCM encrypted at rest",
    },
    "config.hint.smtp.from": {
        "zh-CN": "字符串，例：noreply@example.com",
        "en-US": "String, e.g. noreply@example.com",
    },
    "config.hint.log.level": {
        "zh-CN": "可选值：TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL",
        "en-US": "Allowed: TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL",
    },
    # ==== Skill 生命周期状态标签（V3.0 M2 回加，消费方 review.state_machine.STATUS_LABEL_I18N_KEY）====
    "skill.status.draft": {
        "zh-CN": "草稿",
        "en-US": "Draft",
    },
    "skill.status.pending_review": {
        "zh-CN": "审核中",
        "en-US": "Under Review",
    },
    "skill.status.approved": {
        "zh-CN": "已通过",
        "en-US": "Approved",
    },
    "skill.status.rejected": {
        "zh-CN": "已拒绝",
        "en-US": "Rejected",
    },
    "skill.status.share_iteration": {
        "zh-CN": "分享迭代",
        "en-US": "Share Iteration",
    },
    "skill.status.enabled": {
        "zh-CN": "已启用",
        "en-US": "Enabled",
    },
    "skill.status.disabled": {
        "zh-CN": "停用",
        "en-US": "Disabled",
    },
    "skill.status.withdrawn": {
        "zh-CN": "撤回",
        "en-US": "Withdrawn",
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