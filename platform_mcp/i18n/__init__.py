"""i18n 资源字典 — key → locale 文案（V3.0 M1，架构 §19.5.2）

扩展性约束：新增语言 = 加字典条目 + SUPPORTED_LOCALES 枚举，禁止任何硬编码语言分支。
消费方：系统配置注册表描述/生效语义标签（GET /system-config/registry 按 locale 返回）；
后续里程碑的动态产物（README/审核报告/搜索结果）按同一字典扩展。
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_LOCALE = "zh-CN"
SUPPORTED_LOCALES: tuple[str, ...] = ("zh-CN", "en-US")

RESOURCES: dict[str, dict[str, str]] = {
    # ==== 运行时配置中心：已知键描述 ====
    "config.desc.sys.default_locale": {
        "zh-CN": "系统默认界面语言；仅影响未设置个人语言偏好的用户（如新建用户的初始值），已有个人偏好的用户不受影响（个人设置即时生效且优先）",
        "en-US": "System default UI language; affects only users without a personal language preference (e.g. initial value for new users). Existing preferences are unaffected - personal settings apply instantly and take precedence",
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
    "config.desc.skill.max_upload_size_mb": {
        "zh-CN": "Skill 包上传大小上限（MB）",
        "en-US": "Max Skill package upload size (MB)",
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
    "config.label.skill.max_upload_size_mb": {
        "zh-CN": "Skill 上传大小上限",
        "en-US": "Skill upload size limit",
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
        "zh-CN": "可选值：zh-CN / en-US；仅作用于未设置个人偏好的用户，修改后老用户语言不变",
        "en-US": "Allowed: zh-CN / en-US; applies only to users without a personal preference - changing it never alters existing users' language",
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
    "config.hint.skill.max_upload_size_mb": {
        "zh-CN": "范围 1-2048，单位 MB",
        "en-US": "Range 1-2048, in MB",
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
    # ==== 内置 Skill 功能描述（V3.0 M3R3：双语 README 功能描述按语言取值；装饰器注册 Skill 经 skill_code 命中）====
    "skill.desc.database": {
        "zh-CN": "SQL 执行能力：SQL 文本/文件执行、风险校验、数据源列举、异步状态查询",
        "en-US": "SQL execution: SQL text/file execution, risk validation, datasource listing, and async status query",
    },
    "skill.desc.server": {
        "zh-CN": "Linux SSH/SFTP 能力：shell 命令执行、文件上传下载、命令风控、服务器列举、异步状态",
        "en-US": "Linux SSH/SFTP capabilities: shell command execution, file upload/download, command risk control, server listing, and async status",
    },
    "skill.desc.skill_ecosystem": {
        "zh-CN": "Skill 生态：个人库草稿创建/更新、提审/撤回、分享迭代解决、外部产物回传",
        "en-US": "Skill ecosystem: personal-library draft create/update, review submit/withdraw, share-iteration resolution, and external artifact return",
    },
    "skill.desc.skill_plaza": {
        "zh-CN": "功能广场：语义搜索、相似推荐、README 查看、添加/移除我的 Skill、黑名单管理",
        "en-US": "Skill plaza: semantic search, similar-skill suggestions, README viewing, add/remove my skills, and blacklist management",
    },
    "skill.desc.skill_account": {
        "zh-CN": "个人与查询：Skill 审核（admin）、审计日志查询、个人资料与密码维护",
        "en-US": "Account and queries: skill review (admin), audit-log query, profile and password maintenance",
    },
    # ==== 生效语义标签 ====
    "config.effect.relogin": {
        "zh-CN": "重新登录后生效",
        "en-US": "Effective after re-login",
    },
    "config.effect.new_user_only": {
        "zh-CN": "仅影响未设置个人偏好的用户（如新用户）；个人语言设置即时生效且优先",
        "en-US": "Affects only users without a personal preference (e.g. new users); personal language settings apply instantly and take precedence",
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


#: 「中文 / English」并列文案的 CJK 判定（汉字，含扩展 A；不含假名/谚文——平台并列约定仅中英）
_CJK_PATTERN = re.compile(r"[㐀-鿿]")


def split_bilingual(text: str | None) -> tuple[str, str]:
    """拆分「中文 / English」并列文案为 ``(zh, en)``（M1 工具描述中英并列约定的配套拆分器）。

    分隔符取首个同时满足条件的 ``" / "``：左侧含 CJK（中文段已开始）、右侧不含 CJK
    （英文段起点）——规避描述内部斜杠误切（如工具清单 ``execute_command / upload_file``、
    ``SQL 文本/文件``）。无合法分隔符时两语言同值返回（原文未按约定并列，不强行拆）。
    """
    if not text:
        return "", ""
    for idx in range(len(text) - 2):
        if text[idx : idx + 3] != " / ":
            continue
        zh, en = text[:idx].strip(), text[idx + 3 :].strip()
        if zh and en and _CJK_PATTERN.search(zh) and not _CJK_PATTERN.search(en):
            return zh, en
    return text, text