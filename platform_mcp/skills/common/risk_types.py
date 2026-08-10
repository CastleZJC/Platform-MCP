"""风险类型共用层 — RiskLevel / RiskResult / _LEVEL_ORDER（database + server 共享）"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_LEVEL_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


@dataclass
class RiskResult:
    level: RiskLevel
    reasons: list[str] = field(default_factory=list)
    statement_type: str = "UNKNOWN"

    @property
    def needs_confirm(self) -> bool:
        return self.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
