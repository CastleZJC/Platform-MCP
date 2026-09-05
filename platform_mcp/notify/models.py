"""邮件组提醒 ORM 模型（V3.0 M5，架构 §19.5.5 / migration 009）"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpNotifyGroup(BaseModel):
    """提醒事项组：notify_type 四值 + 参数化模板 + 独立启停（F-39 / F-37 停用静默）。"""

    __tablename__ = "pmcp_notify_group"

    notify_type: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    param_descriptions: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[int] = mapped_column(SmallInteger, server_default="1", nullable=False)

    __table_args__ = ({"comment": "邮件提醒事项组（V3.0 M5）"},)


class PmcpNotifyGroupMember(BaseModel):
    """组成员：仅 admin 角色用户可入组（服务层录入校验 + 无邮箱提示）。"""

    __tablename__ = "pmcp_notify_group_member"

    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_notify_group.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pmcp_user.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        {"comment": "邮件提醒组成员（仅 admin 角色用户，架构 §19.5.5）"},
    )


class PmcpNotifyOutbox(BaseModel):
    """发件箱（outbox 模式）：先落库后发送，失败可重试、全程可审计（F-38）。"""

    __tablename__ = "pmcp_notify_outbox"

    notify_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_user_id: Mapped[int | None] = mapped_column(BigInteger)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="pending", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = ({"comment": "邮件发件箱（outbox 模式，V3.0 M5，F-38）"},)
