"""Skill 审计报告 ORM 模型 + 审计结果数据类"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class Severity(str, Enum):
    """审计规则严重程度"""
    CRITICAL = "critical"    # 🔴 阻止注册
    WARNING = "warning"      # 🟡 标记警告
    SUGGESTION = "suggestion"  # 🟢 仅提示


@dataclass
class AuditRuleResult:
    """单条审计规则检查结果"""
    rule_id: str              # 规则编号，如 "R1-01"
    severity: Severity        # 严重程度
    passed: bool              # 是否通过
    file_path: str = ""       # 违规文件相对路径
    line_number: int = 0      # 违规行号（0 表示文件级）
    description: str = ""     # 问题描述
    suggestion: str = ""      # 修复建议


@dataclass
class AuditResult:
    """Skill 包审计结果"""
    skill_name: str                           # Skill 名称（脱敏后）
    total_rules: int = 14                     # 总规则数
    results: list[AuditRuleResult] = field(default_factory=list)  # 各规则结果
    critical_count: int = 0                   # 🔴 严重命中数
    warning_count: int = 0                    # 🟡 警告命中数
    suggestion_count: int = 0                 # 🟢 建议命中数
    passed: bool = True                       # 是否通过（无 critical 命中即通过）

    def compute_counts(self) -> None:
        """根据 results 重新计算各级别命中数"""
        self.critical_count = sum(1 for r in self.results if not r.passed and r.severity == Severity.CRITICAL)
        self.warning_count = sum(1 for r in self.results if not r.passed and r.severity == Severity.WARNING)
        self.suggestion_count = sum(1 for r in self.results if not r.passed and r.severity == Severity.SUGGESTION)
        self.passed = self.critical_count == 0

    def to_audit_summary(self) -> dict[str, Any]:
        """转换为 JSONB 审计摘要（存入 pmcp_skill.audit_result）"""
        return {
            "total_rules": self.total_rules,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "suggestion_count": self.suggestion_count,
            "passed": self.passed,
            "failed_rules": [
                {"rule_id": r.rule_id, "severity": r.severity.value, "file_path": r.file_path, "line_number": r.line_number}
                for r in self.results if not r.passed
            ],
        }


class PmcpSkillAuditReport(BaseModel):
    __tablename__ = "pmcp_skill_audit_report"

    skill_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_skill.id"), nullable=False, comment="Skill ID")
    audit_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", comment="审计时间")
    auditor: Mapped[str] = mapped_column(String(64), nullable=False, server_default="system", comment="审计者（系统自动为 system）")
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False, comment="规则编号（如 R1-01）")
    severity: Mapped[str] = mapped_column(String(10), nullable=False, comment="严重程度(critical/warning/suggestion)")
    file_path: Mapped[str | None] = mapped_column(String(512), comment="违规文件相对路径")
    line_number: Mapped[int | None] = mapped_column(Integer, comment="违规行号（0 表示文件级）")
    description: Mapped[str | None] = mapped_column(Text, comment="问题描述")
    suggestion: Mapped[str | None] = mapped_column(Text, comment="修复建议")

    __table_args__ = ({"comment": "Skill 审计报告"},)