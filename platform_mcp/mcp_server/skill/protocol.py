"""Skill Protocol 接口定义与 Tool 元数据结构"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolMeta:
    """Tool 元数据 — 对应架构文档 §8.5"""

    tool_name: str
    display_name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    required_permissions: list[str] = field(default_factory=list)
    supported_envs: list[str] = field(default_factory=list)
    risk_level: str = "LOW"
    timeout_seconds: int = 300
    audit_required: bool = True


@runtime_checkable
class SkillProtocol(Protocol):
    """Skill 统一接口 — 对应架构文档 §8.4"""

    def skill_name(self) -> str: ...

    def list_tools(self) -> list[ToolMeta]: ...

    async def validate(self, tool_name: str, params: dict) -> dict: ...

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any: ...

    def support(self, tool_name: str) -> bool: ...
