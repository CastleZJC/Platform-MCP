"""Session 管理 — 内存 dict + TTL"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


@dataclass
class SessionInfo:
    user_id: int
    username: str
    nickname: str | None
    role_code: str
    status: int = 1
    email: str | None = None
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)


class SessionManager:
    def __init__(self, ttl: int = 1800) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._ttl = ttl

    def create(self, user_id: int, username: str, nickname: str | None, role_code: str, status: int = 1, email: str | None = None) -> str:
        self._cleanup()
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = SessionInfo(
            user_id=user_id, username=username, nickname=nickname, role_code=role_code, status=status, email=email
        )
        return session_id

    def get(self, session_id: str) -> SessionInfo | None:
        info = self._sessions.get(session_id)
        if info is None:
            return None
        if time.time() - info.last_access > self._ttl:
            del self._sessions[session_id]
            return None
        info.last_access = time.time()
        return info

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _cleanup(self) -> None:
        now = time.time()
        expired = [sid for sid, info in self._sessions.items() if now - info.last_access > self._ttl]
        for sid in expired:
            del self._sessions[sid]


session_manager = SessionManager()
