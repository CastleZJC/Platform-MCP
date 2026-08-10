"""API Key ORM — pmcp_api_key 表"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import Base


class PmcpApiKey(Base):
    __tablename__ = "pmcp_api_key"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pmcp_user.id"), nullable=False, comment="所属用户")
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, comment="SHA-256 哈希")
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, comment="前8位用于识别")
    key_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="AES 加密后的明文 Key，用于 admin reveal")
    description: Mapped[str | None] = mapped_column(String(255), comment="备注（如：我的台式机）")
    status: Mapped[int] = mapped_column(Integer, default=1, comment="1=活跃 0=已撤销")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近使用时间")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="过期时间")
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
