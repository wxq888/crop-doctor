# -*- coding: utf-8 -*-
"""反馈工单接口：H5 工单 + PC 工单处理（``admin_router``）。

设计依据：``docs/impl-pc-admin-v1.md`` §2.4 / §5。

数据隔离红线：H5 侧所有查询在 SQL 层强制 ``user_id == current_user.id``；
越权访问统一 404 / 6001（不区分「不存在」与「无权」，防探测）。
状态机由 :mod:`app.services.ticket` 集中管理；``closed`` 为终态。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin, get_current_user
from app.core.exceptions import (
    CODE_RECORD_NOT_FOUND,
    CODE_TICKET_NOT_FOUND,
    BusinessError,
)
from app.core.response import ok, page_data
from app.models.detection import DetectionRecord
from app.models.feedback import Feedback, FeedbackMessage
from app.models.user import User
from app.schemas.feedback import (
    AdminFeedbackDetail,
    AdminFeedbackItem,
    FeedbackCreate,
    FeedbackDetail,
    FeedbackItem,
    FeedbackMessageOut,
    FeedbackOut,
    MessageIn,
    RecordBrief,
)
from app.services import severity
from app.services.ticket import ticket_service
from app.utils import storage
from app.utils.classmap import disease_cn_of

# H5 路由（前缀 /feedback）与 PC 路由（前缀 /admin/feedback，由 router 的 _EXTRA 挂载）
router = APIRouter()
admin_router = APIRouter()


# ============================================================
# 内部工具
# ============================================================
def _get_owned_feedback(db: Session, feedback_id: int, user_id: int) -> Feedback:
    """按 id + user_id 取工单；不存在或非本人一律 404 / 6001。"""
    feedback = db.scalar(
        select(Feedback).where(Feedback.id == feedback_id, Feedback.user_id == user_id)
    )
    if feedback is None:
        raise BusinessError(CODE_TICKET_NOT_FOUND, "工单不存在或无权访问", http_status=404)
    return feedback


def _get_feedback(db: Session, feedback_id: int) -> Feedback:
    """管理员按 id 取工单；不存在 404 / 6001。"""
    feedback = db.get(Feedback, feedback_id)
    if feedback is None:
        raise BusinessError(CODE_TICKET_NOT_FOUND, "工单不存在或无权访问", http_status=404)
    return feedback


def _messages(db: Session, feedback_id: int) -> list[FeedbackMessage]:
    """按创建时间升序返回工单全部消息。"""
    return list(
        db.scalars(
            select(FeedbackMessage)
            .where(FeedbackMessage.feedback_id == feedback_id)
            .order_by(FeedbackMessage.created_at.asc(), FeedbackMessage.id.asc())
        ).all()
    )


def _msg_out(message: FeedbackMessage) -> FeedbackMessageOut:
    """FeedbackMessage → 出参。"""
    return FeedbackMessageOut(
        id=message.id,
        feedback_id=message.feedback_id,
        sender_role=message.sender_role,
        sender_id=message.sender_id,
        content=message.content,
        is_read=bool(message.is_read),
        created_at=message.created_at,
    )


def _message_stats(db: Session, feedback_id: int) -> tuple[int, int, int]:
    """返回 ``(总条数, 用户未读(admin 发的), 管理员未读(user 发的))``。"""
    total = db.scalar(
        select(func.count())
        .select_from(FeedbackMessage)
        .where(FeedbackMessage.feedback_id == feedback_id)
    ) or 0
    admin_unread = db.scalar(
        select(func.count())
        .select_from(FeedbackMessage)
        .where(
            FeedbackMessage.feedback_id == feedback_id,
            FeedbackMessage.sender_role == "admin",
            FeedbackMessage.is_read == 0,
        )
    ) or 0
    user_unread = db.scalar(
        select(func.count())
        .select_from(FeedbackMessage)
        .where(
            FeedbackMessage.feedback_id == feedback_id,
            FeedbackMessage.sender_role == "user",
            FeedbackMessage.is_read == 0,
        )
    ) or 0
    return int(total), int(admin_unread), int(user_unread)


def _record_brief(db: Session, record_id: int) -> RecordBrief | None:
    """构造检测样本摘要（result_verdict 工单用）。"""
    record = db.get(DetectionRecord, record_id)
    if record is None:
        return None
    return RecordBrief(
        id=record.id,
        thumb_url=storage.url_of(record.image_path),
        annotated_url=storage.url_of(record.annotated_path),
        top_disease=record.top_disease,
        disease_cn=disease_cn_of(record.top_disease),
        severity_level=record.severity_level,
        severity_label=severity.label_of(record.severity_level),
        top_conf=record.top_conf,
    )


def _feedback_out(db: Session, feedback: Feedback, viewer_is_admin: bool) -> FeedbackOut:
    """构造成员视角的工单头出参（未读数按视角取值）。"""
    total, admin_unread, user_unread = _message_stats(db, feedback.id)
    return FeedbackOut(
        id=feedback.id,
        user_id=feedback.user_id,
        type=feedback.type,
        record_id=feedback.record_id,
        verdict=feedback.verdict,
        correct_disease=feedback.correct_disease,
        title=feedback.title,
        status=feedback.status,
        last_reply_at=feedback.last_reply_at,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
        message_count=total,
        unread_count=user_unread if viewer_is_admin else admin_unread,
    )


def _feedback_detail(db: Session, feedback: Feedback, viewer_is_admin: bool) -> FeedbackDetail:
    """构造工单详情出参（含多轮消息与可选样本）。"""
    base = _feedback_out(db, feedback, viewer_is_admin)
    record = None
    if feedback.record_id is not None:
        record = _record_brief(db, feedback.record_id)
    return FeedbackDetail(
        **base.model_dump(),
        messages=[_msg_out(m) for m in _messages(db, feedback.id)],
        record=record,
    )


async def _publish(event_type: str, data: dict) -> None:
    """发布 monitor 事件（monitor 未落地 / 异常一律静默）。"""
    try:
        from app.services.monitor import publish_event  # noqa: PLC0415 —— 惰性导入
    except Exception:  # noqa: BLE001
        return
    try:
        await publish_event(event_type, data)
    except Exception:  # noqa: BLE001 —— 事件发布失败绝不影响主流程
        pass


# ============================================================
# H5 · 我的工单
# ============================================================
@router.post("", summary="创建工单")
async def create_feedback(
    payload: FeedbackCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """创建工单（``question`` / ``result_verdict``）；关联记录必须属于本人。"""
    if payload.record_id is not None:
        record = db.scalar(
            select(DetectionRecord).where(
                DetectionRecord.id == payload.record_id,
                DetectionRecord.user_id == current_user.id,
            )
        )
        if record is None:
            raise BusinessError(CODE_RECORD_NOT_FOUND, "检测记录不存在或无权访问", http_status=404)

    feedback = ticket_service.create(db, current_user, payload)
    await _publish(
        "feedback.created",
        {
            "feedback_id": feedback.id,
            "type": feedback.type,
            "title": feedback.title,
            "user_id": feedback.user_id,
            "username": current_user.username,
            "record_id": feedback.record_id,
            "status": feedback.status,
            "created_at": _iso(feedback.created_at),
        },
    )
    return ok(_feedback_out(db, feedback, viewer_is_admin=False))


@router.get("/mine", summary="我的工单列表")
def my_feedbacks(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    status: Annotated[str | None, Query(description="按状态筛选 pending/replied/closed")] = None,
    type: Annotated[str | None, Query(description="按类型筛选")] = None,
) -> dict:
    """分页返回本人工单。"""
    conditions = [Feedback.user_id == current_user.id]
    if status:
        conditions.append(Feedback.status == status)
    if type:
        conditions.append(Feedback.type == type)
    total = db.scalar(select(func.count()).select_from(Feedback).where(*conditions)) or 0
    rows = db.scalars(
        select(Feedback)
        .where(*conditions)
        .order_by(Feedback.updated_at.desc(), Feedback.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_item_payload(db, fb, viewer_is_admin=False) for fb in rows]
    return ok(page_data(items, int(total), page, page_size))


@router.get("/unread-count", summary="我的未读工单消息数")
def my_unread_count(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """本人工单中 admin 消息未读条数。"""
    count = ticket_service.unread_count(db, user_id=current_user.id, is_admin=False)
    return ok({"count": count})


@router.get("/{feedback_id}", summary="工单详情（自动置已读）")
def get_feedback(
    feedback_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回本人某工单详情；打开即把管理员消息置为已读。"""
    feedback = _get_owned_feedback(db, feedback_id, current_user.id)
    ticket_service.mark_read_for_user(db, feedback)
    return ok(_feedback_detail(db, feedback, viewer_is_admin=False))


@router.post("/{feedback_id}/messages", summary="用户追问")
async def add_message(
    feedback_id: int,
    payload: MessageIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """用户在工单中追加消息；工单已关闭 → 409 / 6002。"""
    feedback = _get_owned_feedback(db, feedback_id, current_user.id)
    message = ticket_service.add_user_message(db, feedback, current_user, payload.content)
    await _publish(
        "feedback.created",
        {
            "feedback_id": feedback.id,
            "type": feedback.type,
            "title": feedback.title,
            "user_id": feedback.user_id,
            "username": current_user.username,
            "record_id": feedback.record_id,
            "status": feedback.status,
            "created_at": _iso(message.created_at),
        },
    )
    return ok(_msg_out(message))


@router.post("/{feedback_id}/read", summary="标记工单已读")
def mark_read(
    feedback_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """把本人某工单内管理员消息置为已读。"""
    feedback = _get_owned_feedback(db, feedback_id, current_user.id)
    ticket_service.mark_read_for_user(db, feedback)
    return ok(None)


# ============================================================
# PC · 工单处理（管理员）
# ============================================================
@admin_router.get("", summary="工单列表（管理端）")
def admin_list_feedbacks(
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    status: Annotated[str | None, Query(description="按状态筛选")] = None,
    type: Annotated[str | None, Query(description="按类型筛选")] = None,
    keyword: Annotated[str | None, Query(max_length=100, description="按标题/用户名模糊")] = None,
    unread_only: Annotated[bool, Query(description="仅含用户未读消息的工单")] = False,
) -> dict:
    """分页返回全部工单（待回复置顶）。"""
    conditions = []
    if status:
        conditions.append(Feedback.status == status)
    if type:
        conditions.append(Feedback.type == type)
    if keyword:
        conditions.append(Feedback.title.like(f"%{keyword}%"))
    if unread_only:
        sub = select(FeedbackMessage.feedback_id).where(
            FeedbackMessage.sender_role == "user",
            FeedbackMessage.is_read == 0,
        )
        conditions.append(Feedback.id.in_(sub))

    total = db.scalar(select(func.count()).select_from(Feedback).where(*conditions)) or 0
    rows = db.scalars(
        select(Feedback)
        .where(*conditions)
        # 待回复（pending）置顶，其后按最近往来倒序
        .order_by(Feedback.status.asc(), Feedback.updated_at.desc(), Feedback.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_admin_item_payload(db, fb) for fb in rows]
    return ok(page_data(items, int(total), page, page_size))


@admin_router.get("/unread-count", summary="工单未读数（管理端）")
def admin_unread_count(
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """全部工单中 user 消息未读条数。"""
    count = ticket_service.unread_count(db, user_id=None, is_admin=True)
    return ok({"count": count})


@admin_router.get("/{feedback_id}", summary="工单详情（管理端，自动置已读）")
def admin_get_feedback(
    feedback_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回工单详情；打开即把用户消息置为已读。"""
    feedback = _get_feedback(db, feedback_id)
    ticket_service.mark_read_for_admin(db, feedback)
    detail = _feedback_detail(db, feedback, viewer_is_admin=True)
    owner = db.get(User, feedback.user_id)
    out = AdminFeedbackDetail(
        **detail.model_dump(),
        username=owner.username if owner else None,
        nickname=owner.nickname if owner else None,
    )
    return ok(out)


@admin_router.post("/{feedback_id}/reply", summary="管理员回复工单")
async def admin_reply(
    feedback_id: int,
    payload: MessageIn,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """管理员回复；工单已关闭 → 409 / 6002。"""
    feedback = _get_feedback(db, feedback_id)
    message = ticket_service.admin_reply(db, feedback, admin, payload.content)
    await _publish(
        "feedback.replied",
        {
            "feedback_id": feedback.id,
            "admin_id": admin.id,
            "admin_name": admin.nickname or admin.username,
            "to_user_id": feedback.user_id,
            "title": feedback.title,
            "replied_at": _iso(message.created_at),
        },
    )
    return ok(_msg_out(message))


@admin_router.post("/{feedback_id}/close", summary="关闭工单")
def admin_close(
    feedback_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """关闭工单；已关闭 → 409 / 6003。"""
    feedback = _get_feedback(db, feedback_id)
    feedback = ticket_service.close(db, feedback, admin)
    return ok(_feedback_out(db, feedback, viewer_is_admin=True))


# ============================================================
# 列表项载荷
# ============================================================
def _item_payload(db: Session, feedback: Feedback, *, viewer_is_admin: bool) -> dict:
    """工单列表项（H5）。"""
    total, admin_unread, user_unread = _message_stats(db, feedback.id)
    return FeedbackItem(
        id=feedback.id,
        type=feedback.type,
        title=feedback.title,
        status=feedback.status,
        record_id=feedback.record_id,
        last_reply_at=feedback.last_reply_at,
        created_at=feedback.created_at,
        message_count=total,
        unread_count=user_unread if viewer_is_admin else admin_unread,
    ).model_dump()


def _admin_item_payload(db: Session, feedback: Feedback) -> dict:
    """工单列表项（管理端，附用户信息与最新消息摘要）。"""
    base = _item_payload(db, feedback, viewer_is_admin=True)
    owner = db.get(User, feedback.user_id)
    last = db.scalar(
        select(FeedbackMessage)
        .where(FeedbackMessage.feedback_id == feedback.id)
        .order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc())
        .limit(1)
    )
    item = AdminFeedbackItem(
        **base,
        user_id=feedback.user_id,
        username=owner.username if owner else None,
        nickname=owner.nickname if owner else None,
        last_message=(last.content[:80] if last else None),
    )
    return item.model_dump()


def _iso(value) -> str | None:  # noqa: ANN001
    """datetime → ISO-8601 带 Z。"""
    from datetime import timezone

    if value is None:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["router", "admin_router"]
