"""Shell 风险识别引擎 — Linux 命令模式匹配（镜像 skills/database/risk.py 结构）

等级划分（详见 plan §二.4）：
- CRITICAL: rm -rf 根/家目录、mkfs、dd 写块设备、fork bomb、shutdown/reboot、> /dev/sd*、chmod -R 777 /、
            kill init、curl|sh、写 /etc/passwd|shadow|/boot/
- HIGH:     sudo、service/systemctl 重启停止、/etc/ 写、apt remove、yum erase、iptables -F、nc -l、chmod 4755 setuid
- MEDIUM:   curl/wget（无管道到 sh）、nohup 后台、| sh、> 重定向到非白名单
- LOW:      白名单内只读命令（ls/cat/grep/ps/df/top 等）

PROD 环境：HIGH 自动升 CRITICAL（与 database/risk.py 一致）。
"""

from __future__ import annotations

import re

from platform_mcp.skills.common.risk_types import RiskLevel, RiskResult, _LEVEL_ORDER


# CRITICAL 模式 — 不可逆灾难性操作
_CRITICAL_PATTERNS = [
    (re.compile(r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*\s+)?/(?:\s|$|\*)"), "rm -rf 根目录"),
    (re.compile(r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*\s+)?~(?:\s|$|\*)"), "rm -rf 家目录"),
    (re.compile(r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*\s+)?/\s+\*"), "rm -rf /*"),
    (re.compile(r"\bmkfs(?:\.\w+)?\b"), "mkfs 格式化"),
    (re.compile(r"\bdd\s+.*\bof=/dev/(?:sd|nvme|hd|vd|xvd)"), "dd 写块设备"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff|init\s+0)\b"), "关机/重启"),
    (re.compile(r">\s*/dev/(?:sd|nvme|hd|vd|xvd)"), "覆盖块设备"),
    (re.compile(r"\bchmod\s+(?:-R\s+)?[0-7]*777\s+/(?:\s|$)"), "chmod 777 根目录"),
    (re.compile(r"\bkill\s+-9\s+1\b"), "kill init 进程"),
    (re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:bash|sh|zsh)"), "curl/wget 管道到 shell"),
    (re.compile(r">\s*/etc/(?:passwd|shadow|sudoers)\b"), "覆盖关键系统文件"),
    (re.compile(r"\b(?:cp|mv|dd)\s+.*\s+/boot/"), "写 /boot 目录"),
]

# HIGH 模式 — 系统级风险操作
_HIGH_PATTERNS = [
    (re.compile(r"\bsudo\b"), "sudo 提权"),
    (re.compile(r"\b(?:service|systemctl)\s+(?:restart|stop|disable)\b"), "服务重启/停止"),
    (re.compile(r"[>]\s*/etc/"), "写 /etc 目录"),
    (re.compile(r"\b(?:apt|apt-get|yum|dnf)\s+(?:remove|erase|purge)\b"), "卸载系统包"),
    (re.compile(r"\biptables\s+-F\b"), "iptables 清空规则"),
    (re.compile(r"\bnc\s+-l\b"), "nc 监听端口"),
    (re.compile(r"\bchmod\s+[0-7]{4}\s"), "chmod setuid/setgid 位"),
    (re.compile(r"\b(?:userdel|usermod\s+-[a-zA-Z]*L)\b"), "用户删除/锁定"),
    (re.compile(r"\bformat\b", re.IGNORECASE), "format 命令"),
]

# MEDIUM 模式 — 需关注但不强制 confirm
_MEDIUM_PATTERNS = [
    (re.compile(r"\b(?:curl|wget)\b"), "网络下载"),
    (re.compile(r"\bnohup\b"), "nohup 后台运行"),
    (re.compile(r"\|\s*(?:bash|sh|zsh)\b"), "管道到 shell"),
    (re.compile(r"\b(?:rm|mv|cp)\s+.*\s+/"), "操作根目录路径"),
    (re.compile(r"\bchmod\s+[0-7]{3}\s"), "chmod 修改权限"),
    (re.compile(r"\b(?:>|>>)\s*/"), "重定向到根路径"),
]

# LOW 命令白名单 — 安全只读
_LOW_READONLY_COMMANDS = {
    "ls", "cat", "grep", "egrep", "fgrep", "rg", "find", "ps", "df", "du", "top", "htop",
    "tail", "head", "less", "more", "wc", "sort", "uniq", "cut", "awk", "sed", "tr",
    "free", "uptime", "whoami", "id", "hostname", "uname", "date", "cal",
    "echo", "printf", "test", "true", "false",
    "which", "whereis", "type", "file", "stat", "diff", "cmp",
    "env", "printenv", "set", "export",
    "pwd", "cd",
    "ping", "nslookup", "dig", "host", "traceroute", "tracepath",
    "netstat", "ss", "lsof", "fuser",
    "last", "lastlog", "w", "who", "users",
    "dmesg", "journalctl", "iostat", "vmstat", "sar", "mpstat",
    "crontab", "atq", "at",
    "systemctl", "service",  # 注意：仅当参数为 status/list 等只读子命令时；stop/restart 仍会被 HIGH 模式拦
    "git", "svn",
    "python", "python3", "node", "ruby", "perl", "java", "go", "rustc",
    "md5sum", "sha256sum", "sha1sum", "cksum", "cksum", "base64",
    "tree", "basename", "dirname", "realpath", "readlink",
    "history", "alias",
    "getent", "groups",
    "timedatectl", "localectl",
    "nproc", "lscpu", "lsmem", "lspci", "lsusb", "lsblk",
}


class ShellRiskEngine:
    """Shell 命令风险分析器。analyze() 返回 RiskResult。

    实现：
    1. 命令为空 → LOW（EMPTY）
    2. 命中 CRITICAL 模式 → CRITICAL
    3. 命中 HIGH 模式 → HIGH
    4. 命中 MEDIUM 模式 → MEDIUM
    5. 首词在 _LOW_READONLY_COMMANDS 且未命中危险模式 → LOW
    6. 兜底 → HIGH（未知命令保守判定）
    7. PROD 环境：HIGH 自动升 CRITICAL
    """

    def analyze(self, command: str, env_code: str = "DEV", allowed_paths: list[str] | None = None) -> RiskResult:
        cmd = command.strip()
        if not cmd:
            return RiskResult(level=RiskLevel.LOW, statement_type="EMPTY")

        reasons: list[str] = []
        level = self._assess_risk(cmd, reasons)
        stmt_type = self._classify(cmd)

        if env_code == "PROD" and _LEVEL_ORDER[level] >= _LEVEL_ORDER[RiskLevel.HIGH]:
            level = RiskLevel.CRITICAL
            reasons.append("PROD 环境强制 CRITICAL（HIGH 及以上自动升级）")

        return RiskResult(level=level, reasons=reasons, statement_type=stmt_type)

    def _classify(self, command: str) -> str:
        first = command.split()[0] if command.split() else "UNKNOWN"
        return first.upper() if first else "UNKNOWN"

    def _assess_risk(self, command: str, reasons: list[str]) -> RiskLevel:
        for pattern, label in _CRITICAL_PATTERNS:
            if pattern.search(command):
                reasons.append(f"CRITICAL: {label}")
                return RiskLevel.CRITICAL

        for pattern, label in _HIGH_PATTERNS:
            if pattern.search(command):
                reasons.append(f"HIGH: {label}")
                return RiskLevel.HIGH

        for pattern, label in _MEDIUM_PATTERNS:
            if pattern.search(command):
                reasons.append(f"MEDIUM: {label}")
                return RiskLevel.MEDIUM

        first = command.split()[0] if command.split() else ""
        if first in _LOW_READONLY_COMMANDS:
            return RiskLevel.LOW

        reasons.append("未在白名单且无法识别的命令，保守判定 HIGH")
        return RiskLevel.HIGH


shell_risk_engine = ShellRiskEngine()
