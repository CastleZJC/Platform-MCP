"""server skill 高风险二次确认 — 一次性 token，防重放，TTL 过期

镜像 skills/database/confirm.py 结构，仅将 datasource_code 字段改为 server_code、
sql_hash 改为 command_hash（同样取 sha256[:16]）。
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from platform_mcp.skills.common.risk_types import RiskLevel


@dataclass
class ServerConfirmContext:
    tool_name: str
    server_code: str
    command_hash: str
    risk_level: RiskLevel
    created_at: float
    ttl_seconds: int = 300


class ServerConfirmTokenManager:
    _tokens: dict[str, ServerConfirmContext]

    def __init__(self) -> None:
        self._tokens = {}

    def generate(
        self,
        tool_name: str,
        server_code: str,
        command: str,
        risk_level: RiskLevel,
    ) -> str:
        self._cleanup_expired()
        token = secrets.token_urlsafe(32)
        command_hash = hashlib.sha256(command.encode()).hexdigest()[:16]
        self._tokens[token] = ServerConfirmContext(
            tool_name=tool_name,
            server_code=server_code,
            command_hash=command_hash,
            risk_level=risk_level,
            created_at=time.monotonic(),
        )
        return token

    def validate(self, token: str, tool_name: str, server_code: str) -> ServerConfirmContext | None:
        ctx = self._tokens.get(token)
        if ctx is None:
            return None
        if time.monotonic() - ctx.created_at > ctx.ttl_seconds:
            self._tokens.pop(token, None)
            return None
        if ctx.tool_name != tool_name or ctx.server_code != server_code:
            return None
        return ctx

    def consume(self, token: str) -> None:
        self._tokens.pop(token, None)

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        expired = [t for t, ctx in self._tokens.items() if now - ctx.created_at > ctx.ttl_seconds]
        for t in expired:
            del self._tokens[t]


server_confirm_manager = ServerConfirmTokenManager()
