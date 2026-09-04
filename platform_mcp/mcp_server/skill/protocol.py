"""Skill Protocol 接口定义与 Tool 元数据结构"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: V3.0 三角色（架构 §19.5.4）：admin / developer / 一般用户 user（无 database/server 权限）
ROLE_ADMIN = "admin"
ROLE_DEVELOPER = "developer"
ROLE_USER = "user"
#: ToolMeta.roles 缺省值 = 全角色可见（受限工具在各自 _build_tool_meta 显式收窄）
ALL_ROLES: frozenset[str] = frozenset({ROLE_ADMIN, ROLE_DEVELOPER, ROLE_USER})


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
    # V3.0 M3.5（架构 §19.5.7）：可见角色集合，list_tools 与调用路由按认证身份 role_code 动态过滤。
    # 缺省全角色可见；database/server 执行类工具排除一般用户（user），review_skill 仅 admin。
    roles: set[str] = field(default_factory=lambda: set(ALL_ROLES))


@runtime_checkable
class SkillProtocol(Protocol):
    """Skill 统一接口 — 对应架构文档 §8.4"""

    def skill_name(self) -> str: ...

    def list_tools(self) -> list[ToolMeta]: ...

    async def validate(self, tool_name: str, params: dict) -> dict: ...

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any: ...

    def support(self, tool_name: str) -> bool: ...
