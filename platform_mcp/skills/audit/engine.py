"""Skill 合规审计引擎 — 14 条规则实现

规则来源：内部 SkillStandard.md（14 条合规检查规则标准）
5 类 14 条，全部为确定性 Python 实现（正则 + 模式匹配），无需本地大模型。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Sequence

from platform_mcp.skills.audit.models import AuditResult, AuditRuleResult, Severity


# ==================== 规则定义 ====================

# R1-01: 禁止修改 C 盘非 .claude 目录
# 检查 C:\ 或 C:/ 路径，排除路径中包含 .claude 的
_R1_01_C_DRIVE = re.compile(r"[Cc]:[\\/]", re.IGNORECASE)
_R1_01_CLAUDE = re.compile(r"[Cc]:[\\/].*?[.]claude", re.IGNORECASE)

# R3-02: 禁止网络监听 — 更通用的 .bind( / .listen( / .run( 模式
_R3_02_PATTERNS = [
    re.compile(r"\.bind\s*\(", re.IGNORECASE),
    re.compile(r"\.listen\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:Flask|app|django)\.run\s*\(", re.IGNORECASE),
    re.compile(r"http\.server\b", re.IGNORECASE),
    re.compile(r"socketserver\b", re.IGNORECASE),
    re.compile(r"socket\.bind\s*\(", re.IGNORECASE),
    re.compile(r"host\s*=\s*['\"]0\.0\.0\.0['\"]", re.IGNORECASE),
]

# R4-02: 禁止日志暴露敏感信息 — 匹配 print/logging/logger + 敏感词
_R4_02_PRINT = re.compile(
    r"(?:print\s*\(|logging\.\w+\s*\(|logger\.\w+\s*\(|console\.log\s*\()",
    re.IGNORECASE,
)
_R4_02_SENSITIVE = re.compile(r"(?:password|secret|token|key|credential)", re.IGNORECASE)

# R4-01: 禁止硬编码密码/密钥/Token
_R4_01_PATTERNS = re.compile(
    r"(?:password|passwd|api_key|apikey|secret|token)\s*=\s*['\"][^'\"]{3,}['\"]",
    re.IGNORECASE,
)
_R4_01_EXEMPT = re.compile(
    r"(?:xxx+|<\w+>|\$\{.*\}|REPLACE_ME|CHANGE_ME|your[_\s]?(?:password|key|secret)|"
    r"placeholder|示例|example|default)",
    re.IGNORECASE,
)

# R5-03: 禁止硬编码用户路径 — C:\Users\ 排除 .claude（兼容 \\ 双反斜杠转义）
_R5_03_PATTERN = re.compile(r"[Cc]:[\\/]+[Uu]sers[\\/]+", re.IGNORECASE)
_R5_03_CLAUDE = re.compile(r"[Cc]:[\\/]+[Uu]sers[\\/]+.*?[.]claude", re.IGNORECASE)

# R5-04: 危险 shell 命令 — 更宽松的匹配
_R5_04_PATTERNS = [
    re.compile(r"rm\s+-\s*rf\s+/", re.IGNORECASE),       # rm -rf /
    re.compile(r"rm\s+-\s*rf\s+/\*", re.IGNORECASE),       # rm -rf /*
    re.compile(r"[Dd][Ee][Ll]\s+/[Ss]\s+[Cc]:[\\/]", re.IGNORECASE),  # del /s C:\
    re.compile(r"\bformat\s+[Cc]:[\\/]", re.IGNORECASE),  # format C:\
    re.compile(r"\bmkfs\b"),
    re.compile(r":\(\)\{:\|:&\};:"),                     # fork bomb
    re.compile(r"\bdd\s+if="),                           # dd destructive
]

# R1-02: 递归删除
_R1_02_PATTERNS = [
    re.compile(r"rm\s+-\s*rf\b"),
    re.compile(r"del\s+/[sS]\s+/[qQ]\b"),
    re.compile(r"rmdir\s+/[sS]\s+/[qQ]\b"),
    re.compile(r"shutil\.rmtree\b"),
    re.compile(r"Remove-Item\s+.*-Recurse\s+-Force", re.IGNORECASE),
]
_R1_02_EXEMPT = re.compile(r"__pycache__|\.pyc|\.tmp|\.temp|node_modules|\.cache", re.IGNORECASE)

# R1-03: 禁止访问敏感文件
_R1_03_PATTERNS = re.compile(
    r"(?:\.env|credentials|\.ssh[\\/]|id_rsa|\.pem|\.key|\.p12|\.pfx|\.ppk)\b",
    re.IGNORECASE,
)

# R2-01: 禁止直连执行 DML/DDL
_R2_01_DDL_DML = re.compile(
    r"\b(?:DELETE\s+FROM|UPDATE\s+\w+\s+SET|DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE?|"
    r"ALTER\s+TABLE|ALTER\s+DATABASE)\b",
    re.IGNORECASE,
)
_R2_01_AUTO_EXEC = re.compile(
    r"(?:execute|exec|cursor\.\w*execute|\.execute\()\s*\(?\s*[\"']"
    r"(?:DELETE|UPDATE|DROP|TRUNCATE|ALTER)",
    re.IGNORECASE,
)
_R2_01_SCRIPT_EXEMPT = re.compile(r"(?:生成|脚本|供.*审查|review|manual|人工)", re.IGNORECASE)

# R2-02: 禁止硬编码数据库连接信息
_R2_02_PATTERNS = [
    re.compile(r"\b1521\b"),  # Oracle 默认端口
    re.compile(r"jdbc:oracle", re.IGNORECASE),
    re.compile(r"sqlplus\s+\w+/\w+@", re.IGNORECASE),
    re.compile(r"cx_Oracle\.connect\s*\(", re.IGNORECASE),
    re.compile(r"oracledb\.connect\s*\(", re.IGNORECASE),
    re.compile(r"aiomysql\.connect\s*\(", re.IGNORECASE),
]

# R3-01: 禁止外部 HTTP/HTTPS 连接
_R3_01_PATTERNS = [
    re.compile(r"requests\.(get|post|put|delete|patch|head)\s*\(", re.IGNORECASE),
    re.compile(r"urllib\.request\b", re.IGNORECASE),
    re.compile(r"urllib\.urlopen\s*\(", re.IGNORECASE),
    re.compile(r"http\.client\b", re.IGNORECASE),
    re.compile(r"\bcurl\b", re.IGNORECASE),
    re.compile(r"\bwget\b", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"axios\.(get|post|put|delete)\s*\(", re.IGNORECASE),
    re.compile(r"\bhttpx\.(get|post|put|delete)\s*\(", re.IGNORECASE),
]

def _scan_file(relative_path: str, content: str) -> list[tuple[int, str]]:
    """返回 (行号, 行内容) 列表（行号从 1 开始）"""
    lines = content.splitlines()
    return [(i + 1, line) for i, line in enumerate(lines)]


def _check_r1_01(relative_path: str, content: str) -> AuditRuleResult:
    """R1-01: 禁止修改 C 盘非 .claude 目录"""
    for line_no, line in _scan_file(relative_path, content):
        if _R1_01_C_DRIVE.search(line):
            # 路径含 .claude 则豁免
            if _R1_01_CLAUDE.search(line):
                continue
            return AuditRuleResult(
                rule_id="R1-01",
                severity=Severity.CRITICAL,
                passed=False,
                file_path=relative_path,
                line_number=line_no,
                description=f"文件包含 C 盘路径且伴随写/删操作: {line.strip()[:80]}",
                suggestion="使用 %USERPROFILE% 或 ~ 代替硬编码路径，或确保路径在 .claude 目录下",
            )
    return AuditRuleResult(rule_id="R1-01", severity=Severity.CRITICAL, passed=True)


def _check_r1_02(relative_path: str, content: str) -> AuditRuleResult:
    """R1-02: 风险提示：递归删除"""
    for line_no, line in _scan_file(relative_path, content):
        for pattern in _R1_02_PATTERNS:
            if pattern.search(line):
                # 豁免：清理临时目录
                if _R1_02_EXEMPT.search(line):
                    continue
                return AuditRuleResult(
                    rule_id="R1-02",
                    severity=Severity.WARNING,
                    passed=False,
                    file_path=relative_path,
                    line_number=line_no,
                    description=f"包含递归删除命令: {line.strip()[:80]}",
                    suggestion="确认递归删除目标是临时目录（如 __pycache__），否则建议使用更精确的删除方式",
                )
    return AuditRuleResult(rule_id="R1-02", severity=Severity.WARNING, passed=True)


def _check_r1_03(relative_path: str, content: str) -> AuditRuleResult:
    """R1-03: 禁止访问敏感文件"""
    for line_no, line in _scan_file(relative_path, content):
        if _R1_03_PATTERNS.search(line):
            return AuditRuleResult(
                rule_id="R1-03",
                severity=Severity.CRITICAL,
                passed=False,
                file_path=relative_path,
                line_number=line_no,
                description=f"引用敏感文件: {line.strip()[:80]}",
                suggestion="移除对 .env、.ssh、.pem、.key 等敏感文件的直接引用",
            )
    return AuditRuleResult(rule_id="R1-03", severity=Severity.CRITICAL, passed=True)


def _check_r2_01(relative_path: str, content: str) -> AuditRuleResult:
    """R2-01: 禁止直连执行 DML/DDL"""
    has_statement = _R2_01_DDL_DML.search(content)
    has_auto_exec = _R2_01_AUTO_EXEC.search(content)
    if has_statement and has_auto_exec:
        # 豁免：生成供人工审查的脚本
        if _R2_01_SCRIPT_EXEMPT.search(content):
            return AuditRuleResult(rule_id="R2-01", severity=Severity.CRITICAL, passed=True)
        line_no = 0
        for i, line in enumerate(content.splitlines(), 1):
            if _R2_01_DDL_DML.search(line):
                line_no = i
                break
        return AuditRuleResult(
            rule_id="R2-01",
            severity=Severity.CRITICAL,
            passed=False,
            file_path=relative_path,
            line_number=line_no,
            description="包含自动执行的 DML/DDL 语句",
            suggestion="改为生成供人工审查的 SQL 脚本，不要自动执行修改操作",
        )
    return AuditRuleResult(rule_id="R2-01", severity=Severity.CRITICAL, passed=True)


def _check_r2_02(relative_path: str, content: str) -> AuditRuleResult:
    """R2-02: 禁止硬编码数据库连接信息"""
    for line_no, line in _scan_file(relative_path, content):
        for pattern in _R2_02_PATTERNS:
            if pattern.search(line):
                return AuditRuleResult(
                    rule_id="R2-02",
                    severity=Severity.CRITICAL,
                    passed=False,
                    file_path=relative_path,
                    line_number=line_no,
                    description=f"硬编码数据库连接信息: {line.strip()[:80]}",
                    suggestion="使用环境变量或配置文件管理数据库连接信息",
                )
    return AuditRuleResult(rule_id="R2-02", severity=Severity.CRITICAL, passed=True)


def _check_r3_01(relative_path: str, content: str) -> AuditRuleResult:
    """R3-01: 禁止外部 HTTP/HTTPS 连接"""
    for line_no, line in _scan_file(relative_path, content):
        for pattern in _R3_01_PATTERNS:
            if pattern.search(line):
                return AuditRuleResult(
                    rule_id="R3-01",
                    severity=Severity.CRITICAL,
                    passed=False,
                    file_path=relative_path,
                    line_number=line_no,
                    description=f"包含外部 HTTP/HTTPS 连接: {line.strip()[:80]}",
                    suggestion="移除外部 HTTP/HTTPS 请求，Skill 不应与外部服务通信",
                )
    return AuditRuleResult(rule_id="R3-01", severity=Severity.CRITICAL, passed=True)


def _check_r3_02(relative_path: str, content: str) -> AuditRuleResult:
    """R3-02: 禁止网络监听"""
    for line_no, line in _scan_file(relative_path, content):
        for pattern in _R3_02_PATTERNS:
            if pattern.search(line):
                return AuditRuleResult(
                    rule_id="R3-02",
                    severity=Severity.WARNING,
                    passed=False,
                    file_path=relative_path,
                    line_number=line_no,
                    description=f"包含网络监听/端口绑定: {line.strip()[:80]}",
                    suggestion="移除 socket 绑定或 HTTP 服务器代码",
                )
    return AuditRuleResult(rule_id="R3-02", severity=Severity.WARNING, passed=True)


def _check_r4_01(relative_path: str, content: str) -> AuditRuleResult:
    """R4-01: 禁止硬编码密码/密钥/Token"""
    for line_no, line in _scan_file(relative_path, content):
        match = _R4_01_PATTERNS.search(line)
        if match:
            # 检查值是否为占位符豁免
            value_start = match.end() - 1
            value_part = line[value_start:] if value_start < len(line) else ""
            if _R4_01_EXEMPT.search(value_part) or _R4_01_EXEMPT.search(match.group(0)):
                continue
            return AuditRuleResult(
                rule_id="R4-01",
                severity=Severity.CRITICAL,
                passed=False,
                file_path=relative_path,
                line_number=line_no,
                description=f"硬编码密码/密钥/Token: {line.strip()[:80]}",
                suggestion="使用环境变量或占位符（如 <password>、REPLACE_ME）代替明文值",
            )
    return AuditRuleResult(rule_id="R4-01", severity=Severity.CRITICAL, passed=True)


def _check_r4_02(relative_path: str, content: str) -> AuditRuleResult:
    """R4-02: 禁止日志暴露敏感信息"""
    for line_no, line in _scan_file(relative_path, content):
        if _R4_02_PRINT.search(line) and _R4_02_SENSITIVE.search(line):
            return AuditRuleResult(
                rule_id="R4-02",
                severity=Severity.WARNING,
                passed=False,
                file_path=relative_path,
                line_number=line_no,
                description=f"日志/输出中可能包含敏感信息: {line.strip()[:80]}",
                suggestion="避免在 print/logging 中输出密码、密钥或 Token",
            )
    return AuditRuleResult(rule_id="R4-02", severity=Severity.WARNING, passed=True)


def _check_r5_01(file_list: list[str]) -> AuditRuleResult:
    """R5-01: Skill 必须包含 README.md"""
    has_readme = any(f.upper() == "README.MD" or f == "README.md" for f in file_list)
    if not has_readme:
        return AuditRuleResult(
            rule_id="R5-01",
            severity=Severity.SUGGESTION,
            passed=False,
            description="Skill 包缺少 README.md",
            suggestion="建议添加 README.md 说明用途、使用方法和前置条件",
        )
    return AuditRuleResult(rule_id="R5-01", severity=Severity.SUGGESTION, passed=True)


def _check_r5_02(skill_md_content: str | None) -> AuditRuleResult:
    """R5-02: SKILL.md 须有有效 frontmatter"""
    if skill_md_content is None:
        return AuditRuleResult(
            rule_id="R5-02",
            severity=Severity.SUGGESTION,
            passed=False,
            file_path="SKILL.md",
            description="缺少 SKILL.md 文件",
            suggestion="添加 SKILL.md 并包含 YAML frontmatter（name 和 description 字段）",
        )
    if not skill_md_content.strip().startswith("---"):
        return AuditRuleResult(
            rule_id="R5-02",
            severity=Severity.SUGGESTION,
            passed=False,
            file_path="SKILL.md",
            description="SKILL.md 缺少 YAML frontmatter",
            suggestion="在 SKILL.md 开头添加 --- 分隔的 YAML frontmatter",
        )
    try:
        import yaml
        parts = skill_md_content.strip().split("---", 2)
        if len(parts) < 3:
            return AuditRuleResult(
                rule_id="R5-02",
                severity=Severity.SUGGESTION,
                passed=False,
                file_path="SKILL.md",
                description="SKILL.md frontmatter 格式不完整",
                suggestion="确保 frontmatter 以 --- 开头和结尾",
            )
        frontmatter = yaml.safe_load(parts[1])
        if not isinstance(frontmatter, dict):
            return AuditRuleResult(
                rule_id="R5-02",
                severity=Severity.SUGGESTION,
                passed=False,
                file_path="SKILL.md",
                description="SKILL.md frontmatter 不是有效的 YAML 键值对",
                suggestion="确保 frontmatter 包含 name 和 description 字段",
            )
        if "name" not in frontmatter or "description" not in frontmatter:
            missing = [f for f in ("name", "description") if f not in frontmatter]
            return AuditRuleResult(
                rule_id="R5-02",
                severity=Severity.SUGGESTION,
                passed=False,
                file_path="SKILL.md",
                description=f"SKILL.md frontmatter 缺少字段: {', '.join(missing)}",
                suggestion="确保 frontmatter 包含 name 和 description 字段",
            )
    except Exception as e:
        return AuditRuleResult(
            rule_id="R5-02",
            severity=Severity.SUGGESTION,
            passed=False,
            file_path="SKILL.md",
            description=f"SKILL.md frontmatter 解析失败: {e}",
            suggestion="检查 YAML 语法是否正确",
        )
    return AuditRuleResult(rule_id="R5-02", severity=Severity.SUGGESTION, passed=True)


def _check_r5_03(relative_path: str, content: str) -> AuditRuleResult:
    """R5-03: 禁止硬编码用户路径（.claude 除外）"""
    for line_no, line in _scan_file(relative_path, content):
        if _R5_03_PATTERN.search(line):
            # 路径含 .claude 则豁免
            if _R5_03_CLAUDE.search(line):
                continue
            return AuditRuleResult(
                rule_id="R5-03",
                severity=Severity.CRITICAL,
                passed=False,
                file_path=relative_path,
                line_number=line_no,
                description=f"硬编码用户路径: {line.strip()[:80]}",
                suggestion="使用 ~ 或 %USERPROFILE% 环境变量代替硬编码路径，或确保路径在 .claude 目录下",
            )
    return AuditRuleResult(rule_id="R5-03", severity=Severity.CRITICAL, passed=True)


def _check_r5_04(relative_path: str, content: str) -> AuditRuleResult:
    """R5-04: 危险 shell 命令防护"""
    for line_no, line in _scan_file(relative_path, content):
        for pattern in _R5_04_PATTERNS:
            if pattern.search(line):
                return AuditRuleResult(
                    rule_id="R5-04",
                    severity=Severity.CRITICAL,
                    passed=False,
                    file_path=relative_path,
                    line_number=line_no,
                    description=f"包含危险 shell 命令: {line.strip()[:80]}",
                    suggestion="移除破坏性 shell 命令（如 rm -rf /、mkfs、fork bomb）",
                )
    return AuditRuleResult(rule_id="R5-04", severity=Severity.CRITICAL, passed=True)


# ==================== 审计入口 ====================

def audit_skill_package(
    skill_dir: str | Path,
    skill_name: str,
) -> AuditResult:
    """对解压后的 Skill 包目录执行全部 14 条审计规则。

    Args:
        skill_dir: 解压后的 Skill 包根目录路径
        skill_name: Skill 名称（脱敏后）

    Returns:
        AuditResult 包含所有规则检查结果和汇总
    """
    skill_path = Path(skill_dir)
    result = AuditResult(skill_name=skill_name)

    # 收集所有文本文件内容
    file_contents: dict[str, str] = {}
    all_file_names: list[str] = []
    skill_md_content: str | None = None

    for root, _dirs, files in os.walk(skill_path):
        # 跳过 __pycache__ 和 .git 等目录
        rel_root = Path(root).relative_to(skill_path)
        if any(part.startswith("__pycache__") or part == ".git" for part in rel_root.parts):
            continue
        for fname in files:
            rel_path = str(rel_root / fname).replace("\\", "/")
            all_file_names.append(Path(rel_path).name)
            full_path = Path(root) / fname
            # SKILL.md 特殊处理
            if fname.upper() == "SKILL.MD":
                try:
                    skill_md_content = full_path.read_text(encoding="utf-8")
                except Exception:
                    skill_md_content = None
            # 只扫描文本文件
            try:
                content = full_path.read_text(encoding="utf-8")
                file_contents[rel_path] = content
            except (UnicodeDecodeError, OSError):
                continue

    # R5-01: 检查 README.md 是否存在
    result.results.append(_check_r5_01(all_file_names))

    # R5-02: 检查 SKILL.md frontmatter
    result.results.append(_check_r5_02(skill_md_content))

    # 逐文件扫描文本内容规则
    for rel_path, content in file_contents.items():
        result.results.append(_check_r1_01(rel_path, content))
        result.results.append(_check_r1_02(rel_path, content))
        result.results.append(_check_r1_03(rel_path, content))
        result.results.append(_check_r2_01(rel_path, content))
        result.results.append(_check_r2_02(rel_path, content))
        result.results.append(_check_r3_01(rel_path, content))
        result.results.append(_check_r3_02(rel_path, content))
        result.results.append(_check_r4_01(rel_path, content))
        result.results.append(_check_r4_02(rel_path, content))
        result.results.append(_check_r5_03(rel_path, content))
        result.results.append(_check_r5_04(rel_path, content))

    # 合并同类规则结果（只保留不通过的，且保留最严重的）
    merged: dict[str, AuditRuleResult] = {}
    for r in result.results:
        if not r.passed:
            key = r.rule_id
            if key in merged:
                # 保留更严重的：critical > warning > suggestion
                severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.SUGGESTION: 2}
                if severity_order.get(r.severity, 99) < severity_order.get(merged[key].severity, 99):
                    merged[key] = r
            else:
                merged[key] = r
    # 补充通过的结果
    all_rule_ids = {
        "R1-01", "R1-02", "R1-03", "R2-01", "R2-02",
        "R3-01", "R3-02", "R4-01", "R4-02",
        "R5-01", "R5-02", "R5-03", "R5-04",
    }
    final_results: list[AuditRuleResult] = []
    for rid in sorted(all_rule_ids):
        if rid in merged:
            final_results.append(merged[rid])
        else:
            # 根据规则 ID 确定默认严重程度
            severity = _rule_severity(rid)
            final_results.append(AuditRuleResult(rule_id=rid, severity=severity, passed=True))

    result.results = final_results
    result.compute_counts()
    return result


def _rule_severity(rule_id: str) -> Severity:
    """根据规则 ID 返回默认严重程度"""
    critical_rules = {"R1-01", "R1-03", "R2-01", "R2-02", "R3-01", "R4-01", "R5-03", "R5-04"}
    warning_rules = {"R1-02", "R3-02", "R4-02"}
    suggestion_rules = {"R5-01", "R5-02"}
    if rule_id in critical_rules:
        return Severity.CRITICAL
    if rule_id in warning_rules:
        return Severity.WARNING
    if rule_id in suggestion_rules:
        return Severity.SUGGESTION
    return Severity.WARNING  # 未知规则默认警告