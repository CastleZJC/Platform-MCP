"""高风险二次确认机制 — 一次性 token，防重放，TTL 过期"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from platform_mcp.skills.database.risk import RiskLevel


@dataclass
class ConfirmContext:
    tool_name: str
    datasource_code: str
    sql_hash: str
    risk_level: RiskLevel
    created_at: float
    ttl_seconds: int = 300


class ConfirmTokenManager:
    _tokens: dict[str, ConfirmContext]

    def __init__(self) -> None:
        self._tokens = {}

    def generate(
        self,
        tool_name: str,
        datasource_code: str,
        sql: str,
        risk_level: RiskLevel,
    ) -> str:
        self._cleanup_expired()
        token = secrets.token_urlsafe(32)
        sql_hash = hashlib.sha256(sql.encode()).hexdigest()[:16]
        self._tokens[token] = ConfirmContext(
            tool_name=tool_name,
            datasource_code=datasource_code,
            sql_hash=sql_hash,
            risk_level=risk_level,
            created_at=time.monotonic(),
        )
        return token

    def validate(self, token: str, tool_name: str, datasource_code: str) -> ConfirmContext | None:
        ctx = self._tokens.get(token)
        if ctx is None:
            return None
        if time.monotonic() - ctx.created_at > ctx.ttl_seconds:
            self._tokens.pop(token, None)
            return None
        if ctx.tool_name != tool_name or ctx.datasource_code != datasource_code:
            return None
        return ctx

    def consume(self, token: str) -> None:
        self._tokens.pop(token, None)

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        expired = [t for t, ctx in self._tokens.items() if now - ctx.created_at > ctx.ttl_seconds]
        for t in expired:
            del self._tokens[t]


confirm_manager = ConfirmTokenManager()
