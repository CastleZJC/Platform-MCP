"""Skill 包内部引用脱敏检查模块

检查 Skill 包内容是否含部署方内部信息：
- Skill 名称含配置前缀 → 自动去除
- 内容含配置关键字（公司名/项目名等）→ 标记 R3-01 扩展严重
- 内容含配置内部 IP/域名 → 标记 R3-01 扩展严重

模式来源：模块级 `_SENSITIVE_*` 列表（默认空，由部署方在运行时
按需 monkeypatch 或在初始化阶段注入）。本模块自身不写死任何特定
公司/项目标识，避免引入新的敏感字面量。
"""

from __future__ import annotations

import re
from pathlib import Path

from platform_mcp.skills.audit.models import AuditRuleResult, Severity


# 可由部署方/测试在运行时注入的敏感模式（默认空，不阻塞任何 Skill）
_SENSITIVE_PREFIXES: list[str] = []
_SENSITIVE_KEYWORDS: list[str] = []
_SENSITIVE_DOMAINS: list[str] = []

# RFC 1918 私有 IP（行业通用合规规则，非内部信息，保留内置检测）
_PRIVATE_IP_PATTERNS = [
    re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
]


def _compile_prefix_patterns() -> list[re.Pattern]:
    return [re.compile(rf"^{re.escape(p)}[_-]", re.IGNORECASE) for p in _SENSITIVE_PREFIXES]


def _compile_keyword_patterns() -> list[re.Pattern]:
    return [re.compile(re.escape(k), re.IGNORECASE) for k in _SENSITIVE_KEYWORDS]


def _compile_domain_patterns() -> list[re.Pattern]:
    return [re.compile(re.escape(d), re.IGNORECASE) for d in _SENSITIVE_DOMAINS]


def sanitize_skill_name(name: str) -> tuple[str, bool]:
    """若 name 含配置前缀则去除（含分隔符一并去掉）。

    Args:
        name: 原始 Skill 名称

    Returns:
        (sanitized_name, was_sanitized)
    """
    for pat in _compile_prefix_patterns():
        if pat.match(name):
            sanitized = pat.sub("", name, count=1)
            if sanitized.startswith("-") or sanitized.startswith("_"):
                sanitized = sanitized[1:]
            return sanitized, True
    return name, False


def check_sanitization(
    skill_dir: str | Path,
    skill_name: str,
    file_contents: dict[str, str] | None = None,
) -> list[AuditRuleResult]:
    """扫描 Skill 包内容中的内部引用 / 敏感信息。

    Args:
        skill_dir: 解压后的 Skill 包根目录路径
        skill_name: 原始 Skill 名称（可能含配置前缀）
        file_contents: 可选的预加载文件内容 {相对路径: 内容}

    Returns:
        审计结果列表（R3-01 扩展规则结果）
    """
    results: list[AuditRuleResult] = []
    skill_path = Path(skill_dir)

    if file_contents is None:
        import os
        file_contents = {}
        for root, _dirs, files in os.walk(skill_path):
            rel_root = Path(root).relative_to(skill_path)
            if any(part.startswith("__pycache__") or part == ".git" for part in rel_root.parts):
                continue
            for fname in files:
                rel_path = str(rel_root / fname).replace("\\", "/")
                full_path = Path(root) / fname
                try:
                    file_contents[rel_path] = full_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue

    keyword_patterns = _compile_keyword_patterns()
    domain_patterns = _compile_domain_patterns()
    ip_patterns = list(_PRIVATE_IP_PATTERNS)

    for rel_path, content in file_contents.items():
        lines = content.splitlines()
        reported_categories: set[str] = set()

        def _report(category: str, pattern_src: str, line_no: int, line: str, kind: str) -> None:
            if category in reported_categories:
                return
            results.append(AuditRuleResult(
                rule_id="R3-01",
                severity=Severity.CRITICAL,
                passed=False,
                file_path=rel_path,
                line_number=line_no,
                description=f"包含{kind}: {line.strip()[:80]}",
                suggestion=f"移除 {kind} 后重新上传",
            ))
            reported_categories.add(category)

        for pat, src in zip(keyword_patterns, _SENSITIVE_KEYWORDS):
            for line_no, line in enumerate(lines, 1):
                if pat.search(line):
                    _report(f"keyword:{src}", src, line_no, line, "内部引用")
                    break

        for pat, src in zip(domain_patterns, _SENSITIVE_DOMAINS):
            for line_no, line in enumerate(lines, 1):
                if pat.search(line):
                    _report(f"domain:{src}", src, line_no, line, "内部域名")
                    break

        for idx, pat in enumerate(ip_patterns):
            for line_no, line in enumerate(lines, 1):
                if pat.search(line):
                    _report(f"ip:{idx}", pat.pattern, line_no, line, "私有 IP 地址")
                    break

    return results
