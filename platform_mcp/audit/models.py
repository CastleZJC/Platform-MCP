"""审计日志 ORM 模型"""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_mcp.common.database import BaseModel


class PmcpAuditLog(BaseModel):
    __tablename__ = "pmcp_audit_log"

    trace_id: Mapped[str | None] = mapped_column(String(64), comment="全链路追踪标识")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="请求唯一标识")
    operator: Mapped[str | None] = mapped_column(String(64), comment="操作人")
    skill_name: Mapped[str | None] = mapped_column(String(64), comment="Skill 名称")
    tool_name: Mapped[str | None] = mapped_column(String(64), comment="Tool 名称")
    resource_type: Mapped[str | None] = mapped_column(String(64), comment="资源类型")
    resource_id: Mapped[str | None] = mapped_column(String(128), comment="资源标识")
    env_code: Mapped[str | None] = mapped_column(String(32), comment="环境标识")
    request_summary: Mapped[str | None] = mapped_column(Text, comment="请求摘要")
    result_status: Mapped[str | None] = mapped_column(String(32), comment="结果状态(success/error；V1.0.2 起统一为 error，历史 fail 已 backfill)")
    risk_level: Mapped[str | None] = mapped_column(String(16), comment="风险等级(LOW/MEDIUM/HIGH/CRITICAL)")
    error_code: Mapped[str | None] = mapped_column(String(32), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, comment="耗时毫秒")
    extra_data: Mapped[dict | None] = mapped_column(JSONB, comment="扩展数据(JSONB)")

    __table_args__ = ({"comment": "审计日志"},)


class PmcpMcpCallLog(BaseModel):
    __tablename__ = "pmcp_mcp_call_log"

    trace_id: Mapped[str | None] = mapped_column(String(64), comment="全链路追踪标识")
    tool_name: Mapped[str | None] = mapped_column(String(64), comment="Tool 名称")
    caller: Mapped[str | None] = mapped_column(String(128), comment="调用方(Claude Code)")
    datasource_code: Mapped[str | None] = mapped_column(String(64), comment="数据源编码")
    env_code: Mapped[str | None] = mapped_column(String(32), comment="环境标识")
    input_summary: Mapped[str | None] = mapped_column(Text, comment="输入摘要")
    output_summary: Mapped[str | None] = mapped_column(Text, comment="输出摘要")
    result_status: Mapped[str | None] = mapped_column(String(32), comment="结果状态(success/error)")
    error_code: Mapped[str | None] = mapped_column(String(32), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, comment="耗时毫秒")
    confirm_token: Mapped[str | None] = mapped_column(String(128), comment="确认令牌")
    extra_data: Mapped[dict | None] = mapped_column(JSONB, comment="扩展数据")

    __table_args__ = ({"comment": "MCP 调用日志"},)


class PmcpCryptoOperationLog(BaseModel):
    __tablename__ = "pmcp_crypto_operation_log"

    operator: Mapped[str | None] = mapped_column(String(64), comment="操作人")
    operation_type: Mapped[str | None] = mapped_column(String(32), comment="操作类型(encrypt/decrypt)")
    datasource_code: Mapped[str | None] = mapped_column(String(64), comment="关联数据源编码")
    algorithm: Mapped[str | None] = mapped_column(String(32), comment="算法(AES-256-GCM/AES-256-CBC)")
    result_status: Mapped[str | None] = mapped_column(String(32), comment="结果状态(success/error)")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")

    __table_args__ = ({"comment": "加解密操作日志"},)
