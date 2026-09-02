"""Session 管理 — 内存 dict + TTL（V3.0 M1：TTL/语言随会话快照，重新登录生效）"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

DEFAULT_SESSION_TTL_SECONDS = 1800


@dataclass
class SessionInfo:
    user_id: int
    username: str
    nickname: str | None
    role_code: str
    status: int = 1
    email: str | None = None
    locale: str | None = None
    # TTL 登录时快照（session.timeout_minutes 重新登录生效，运行期改配置不影响存量会话）
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)


class SessionManager:
    def __init__(self, ttl: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._ttl = ttl

    def create(
        self,
        user_id: int,
        username: str,
        nickname: str | None,
        role_code: str,
        status: int = 1,
        email: str | None = None,
        locale: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        self._cleanup()
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = SessionInfo(
            user_id=user_id,
            username=username,
            nickname=nickname,
            role_code=role_code,
            status=status,
            email=email,
            locale=locale,
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self._ttl,
        )
        return session_id

    def get(self, session_id: str) -> SessionInfo | None:
        info = self._sessions.get(session_id)
        if info is None:
            return None
        if time.time() - info.last_access > info.ttl_seconds:
            del self._sessions[session_id]
            return None
        info.last_access = time.time()
        return info

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _cleanup(self) -> None:
        now = time.time()
        expired = [sid for sid, info in self._sessions.items() if now - info.last_access > info.ttl_seconds]
        for sid in expired:
            del self._sessions[sid]


session_manager = SessionManager()