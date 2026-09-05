"""邮件提醒管理 API（V3.0 M5，架构 §19.5.5 / 计划 5.4；admin only，仅 Web 无 MCP 工具）

- 四提醒事项组：启停 / 模板编辑（subject/body + 参数说明）/ 成员管理（仅 admin 角色可入组，
  无邮箱录入时提示，F-37）；
- outbox 发送记录：分页 + 状态筛选（F-38 可审计）；
- 测试发送：指定收件人写 outbox（source=test）并立即 flush 一轮，SMTP 连通性验证（R-13）。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import require_admin
from platform_mcp.auth.models import PmcpRole, PmcpUser, PmcpUserRole
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.notify.models import PmcpNotifyGroup, PmcpNotifyGroupMember, PmcpNotifyOutbox
from platform_mcp.notify.service import NOTIFY_TYPES

router = APIRouter(prefix="/notify", tags=["邮件提醒"])


class GroupUpdateRequest(BaseModel):
    group_name: str | None = None
    enabled: int | None = None
    subject_template: str | None = None
    body_template: str | None = None
    param_descriptions: dict | None = None


class MemberAddRequest(BaseModel):
    user_id: int


class TestSendRequest(BaseModel):
    recipient: str


async def _get_group(db: AsyncSession, notify_type: str) -> PmcpNotifyGroup | None:
    if notify_type not in NOTIFY_TYPES:
        return None
    return (
        await db.execute(select(PmcpNotifyGroup).where(PmcpNotifyGroup.notify_type == notify_type))
    ).scalar_one_or_none()


async def _group_members_detail(db: AsyncSession, group_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(
                PmcpNotifyGroupMember.id,
                PmcpNotifyGroupMember.user_id,
                PmcpUser.username,
                PmcpUser.nickname,
                PmcpUser.email,
            )
            .join(PmcpUser, PmcpUser.id == PmcpNotifyGroupMember.user_id)
            .where(PmcpNotifyGroupMember.group_id == group_id)
            .order_by(PmcpNotifyGroupMember.id)
        )
    ).all()
    return [
        {
            "member_id": r.id,
            "user_id": r.user_id,
            "username": r.username,
            "nickname": r.nickname,
            "email": r.email,
            "has_email": bool(r.email),
        }
        for r in rows
    ]


@router.get("/groups")
async def list_groups(db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)):
    """四提醒事项组列表（含成员明细 / 模板 / 参数说明 / 启停状态，管理页主数据）。"""
    groups = (
        await db.execute(select(PmcpNotifyGroup).order_by(PmcpNotifyGroup.id))
    ).scalars().all()
    items = []
    for g in groups:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(PmcpNotifyOutbox)
                .where(PmcpNotifyOutbox.notify_type == g.notify_type, PmcpNotifyOutbox.status != "sent")
            )
        ).scalar() or 0
        items.append(
            {
                "notify_type": g.notify_type,
                "group_name": g.group_name,
                "subject_template": g.subject_template,
                "body_template": g.body_template,
                "param_descriptions": g.param_descriptions or {},
                "enabled": g.enabled,
                "members": await _group_members_detail(db, g.id),
                "unsent_count": pending,
                "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            }
        )
    return ResponseBase(data=items)


@router.put("/groups/{notify_type}")
async def update_group(
    notify_type: str,
    body: GroupUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """更新组配置：启停 / 组名 / 模板 / 参数说明（F-37 停用静默 / F-39 模板可编辑）。"""
    start = time.monotonic()
    group = await _get_group(db, notify_type)
    if group is None:
        return ResponseBase(code=13001, message=f"通知组不存在：{notify_type}")
    if body.enabled is not None and body.enabled not in (0, 1):
        return ResponseBase(code=13002, message="enabled 仅支持 0/1")
    changes: list[str] = []
    if body.group_name is not None:
        group.group_name = body.group_name
        changes.append("group_name")
    if body.enabled is not None:
        group.enabled = body.enabled
        changes.append(f"enabled={body.enabled}")
    if body.subject_template is not None:
        group.subject_template = body.subject_template
        changes.append("subject_template")
    if body.body_template is not None:
        group.body_template = body.body_template
        changes.append("body_template")
    if body.param_descriptions is not None:
        group.param_descriptions = body.param_descriptions
        changes.append("param_descriptions")
    group.updated_by = _admin["username"]
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="notify",
        resource_id=notify_type,
        request_summary=f"更新邮件提醒组: {notify_type}（{', '.join(changes) or '无变更'}）",
        result_status="success",
        extra_data={"notify_type": notify_type, "changes": changes},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="通知组已更新")


@router.post("/groups/{notify_type}/members")
async def add_member(
    notify_type: str,
    body: MemberAddRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """添加组成员：仅 admin 角色用户可入组（录入校验）；未配置邮箱允许入组但提示（§19.5.5）。"""
    start = time.monotonic()
    group = await _get_group(db, notify_type)
    if group is None:
        return ResponseBase(code=13001, message=f"通知组不存在：{notify_type}")
    user = await db.get(PmcpUser, body.user_id)
    if user is None:
        return ResponseBase(code=13003, message="用户不存在")
    role_code = (
        await db.execute(
            select(PmcpRole.role_code)
            .join(PmcpUserRole, PmcpUserRole.role_id == PmcpRole.id)
            .where(PmcpUserRole.user_id == user.id)
        )
    ).scalar_one_or_none()
    if role_code != "admin":
        return ResponseBase(code=13004, message=f"仅 admin 角色用户可入组（{user.username} 当前角色：{role_code or '无'}）")
    existing = (
        await db.execute(
            select(PmcpNotifyGroupMember).where(
                PmcpNotifyGroupMember.group_id == group.id,
                PmcpNotifyGroupMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ResponseBase(code=13005, message="该用户已在组内")
    db.add(
        PmcpNotifyGroupMember(
            group_id=group.id, user_id=user.id, inserted_by=_admin["username"]
        )
    )
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="notify",
        resource_id=notify_type,
        request_summary=f"邮件提醒组添加成员: {notify_type} + {user.username}",
        result_status="success",
        extra_data={"notify_type": notify_type, "added_user": user.username},
        duration_ms=duration_ms,
    )
    message = "成员已添加"
    if not user.email:
        message += "（提示：该用户未配置邮箱，发送时将被跳过，请在用户管理中补充邮箱）"
    return ResponseBase(message=message)


@router.delete("/groups/{notify_type}/members/{user_id}")
async def remove_member(
    notify_type: str,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """移除组成员。"""
    start = time.monotonic()
    group = await _get_group(db, notify_type)
    if group is None:
        return ResponseBase(code=13001, message=f"通知组不存在：{notify_type}")
    member = (
        await db.execute(
            select(PmcpNotifyGroupMember).where(
                PmcpNotifyGroupMember.group_id == group.id,
                PmcpNotifyGroupMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        return ResponseBase(code=13006, message="该用户不在组内")
    await db.delete(member)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    username = (
        await db.execute(select(PmcpUser.username).where(PmcpUser.id == user_id))
    ).scalar_one_or_none()
    await write_audit_log(
        operator=_admin["username"],
        resource_type="notify",
        resource_id=notify_type,
        request_summary=f"邮件提醒组移除成员: {notify_type} - {username or user_id}",
        result_status="success",
        extra_data={"notify_type": notify_type, "removed_user_id": user_id},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="成员已移除")


@router.get("/outbox")
async def list_outbox(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    notify_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """发件箱记录（F-38 可审计）：分页 + status/notify_type 筛选，倒序。"""
    query = select(PmcpNotifyOutbox)
    count_query = select(func.count()).select_from(PmcpNotifyOutbox)
    if status:
        query, count_query = query.where(PmcpNotifyOutbox.status == status), \
            count_query.where(PmcpNotifyOutbox.status == status)
    if notify_type:
        query, count_query = query.where(PmcpNotifyOutbox.notify_type == notify_type), \
            count_query.where(PmcpNotifyOutbox.notify_type == notify_type)
    total = (await db.execute(count_query)).scalar() or 0
    query = (
        query.order_by(PmcpNotifyOutbox.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(query)).scalars().all()
    items = [
        {
            "id": r.id,
            "notify_type": r.notify_type,
            "source": r.source,
            "recipient": r.recipient,
            "subject": r.subject,
            "body": r.body,
            "status": r.status,
            "retry_count": r.retry_count,
            "error_message": r.error_message,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "created_at": r.inserted_at.isoformat() if r.inserted_at else None,
        }
        for r in rows
    ]
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("/test")
async def test_send(
    body: TestSendRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """测试发送：指定收件人落 outbox（source=test）并立即 flush 一轮（SMTP 连通性验证，R-13）。"""
    start = time.monotonic()
    recipient = body.recipient.strip()
    if not recipient or "@" not in recipient:
        return ResponseBase(code=13007, message="收件人邮箱格式不合法")
    db.add(
        PmcpNotifyOutbox(
            notify_type="user_mgmt",
            source="test",
            recipient=recipient,
            recipient_user_id=_admin.get("id"),
            subject="【Platform-MCP】测试邮件（邮件提醒连通性验证）",
            body="这是一封测试邮件：收到即表示 SMTP 配置与发送链路正常。\n"
                 "触发人：{0}\n来源：邮件提醒管理页「发送测试」".format(_admin["username"]),
            inserted_by=_admin["username"],
        )
    )
    await db.commit()
    from platform_mcp.notify.sender import flush_outbox

    result = await flush_outbox()
    duration_ms = int((time.monotonic() - start) * 1000)
    # sent>0=已发；pending>0=SMTP 未配置但已入 outbox 待发（链路正常）；均否=发送失败
    smtp_ready = result["sent"] > 0 or result["pending"] > 0
    await write_audit_log(
        operator=_admin["username"],
        resource_type="notify",
        resource_id="test",
        request_summary=f"发送测试邮件: {recipient}",
        result_status="success" if smtp_ready else "warning",
        extra_data={"recipient": recipient, "flush_result": result},
        duration_ms=duration_ms,
    )
    return ResponseBase(
        data=result,
        message="测试邮件已发送" if result["sent"] else
                ("SMTP 未配置，测试邮件已入 outbox 待发（请先在系统配置页配置 smtp.*）"
                 if result["pending"] else "发送失败，请检查 SMTP 配置与收件人地址（详情见发送记录）"),
    )
