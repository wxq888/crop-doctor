# -*- coding: utf-8 -*-
"""工单状态机服务：``feedbacks``（头）× ``feedback_messages``（多轮往来）。

设计依据：``docs/impl-pc-admin-v1.md`` §5。

状态迁移：``pending → replied → closed``；用户追问可从 ``replied`` 复位为 ``pending``；
``closed`` 为终态，任何回复/追问被拒（``409 / 6002``）。状态机集中于此，便于测试。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import (
    CODE_TICKET_BAD_STATE,
    CODE_TICKET_CLOSED,
    BusinessError,
)
from app.models.feedback import Feedback, FeedbackMessage
from app.models.user import User
from app.schemas.feedback import FeedbackCreate


def _now() -> datetime:
    """当前 UTC 时间（naive，与数据库时间口径一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TicketService:
    """工单状态机（纯业务逻辑，无 HTTP 依赖）。"""

    def create(self, db: Session, user: User, payload: FeedbackCreate) -> Feedback:
        """新建工单：落 head（``status=pending``）+ 首条用户消息。"""
        feedback = Feedback(
            user_id=user.id,
            type=payload.type,
            record_id=payload.record_id,
            verdict=payload.verdict,
            correct_disease=payload.correct_disease,
            title=payload.title,
            status="pending",
        )
        db.add(feedback)
        db.flush()  # 取 feedback.id

        message = FeedbackMessage(
            feedback_id=feedback.id,
            sender_role="user",
            sender_id=user.id,
            content=payload.content,
            is_read=0,
        )
        db.add(message)
        db.commit()
        db.refresh(feedback)
        return feedback

    def add_user_message(
        self, db: Session, feedback: Feedback, user: User, content: str
    ) -> FeedbackMessage:
        """用户追问：``pending/replied`` → 追加消息并把 status 复位为 ``pending``。

        ``closed`` → ``409 / 6002``。
        """
        self._ensure_open(feedback)
        message = FeedbackMessage(
            feedback_id=feedback.id,
            sender_role="user",
            sender_id=user.id,
            content=content,
            is_read=0,
        )
        db.add(message)
        feedback.status = "pending"  # 重新进入待回复
        db.commit()
        db.refresh(message)
        return message

    def admin_reply(
        self, db: Session, feedback: Feedback, admin: User, content: str
    ) -> FeedbackMessage:
        """管理员回复：``pending/replied`` → 追加 admin 消息、``status=replied``、``last_reply_at=now``。

        ``closed`` → ``409 / 6002``。
        """
        self._ensure_open(feedback)
        message = FeedbackMessage(
            feedback_id=feedback.id,
            sender_role="admin",
            sender_id=admin.id,
            content=content,
            is_read=0,
        )
        db.add(message)
        feedback.status = "replied"
        feedback.last_reply_at = _now()
        db.commit()
        db.refresh(message)
        return message

    def close(self, db: Session, feedback: Feedback, admin: User) -> Feedback:
        """关闭工单：``pending/replied`` → ``closed``；已 ``closed`` → ``409 / 6003``（非法流转）。"""
        if feedback.status == "closed":
            raise BusinessError(
                CODE_TICKET_BAD_STATE, "工单状态非法流转：已是关闭状态", http_status=409
            )
        feedback.status = "closed"
        db.commit()
        db.refresh(feedback)
        return feedback

    @staticmethod
    def _ensure_open(feedback: Feedback) -> None:
        """工单已关闭 → 抛 ``409 / 6002``。"""
        if feedback.status == "closed":
            raise BusinessError(
                CODE_TICKET_CLOSED, "工单已关闭，不可继续回复", http_status=409
            )

    def unread_count(self, db: Session, *, user_id: int | None, is_admin: bool) -> int:
        """未读数：

        * 用户（``is_admin=False``）= 本人工单中 ``sender_role='admin' AND is_read=0``；
        * 管理员（``is_admin=True``）= 全部工单中 ``sender_role='user' AND is_read=0``。
        """
        stmt = select(func.count()).select_from(FeedbackMessage)
        if is_admin:
            stmt = stmt.where(
                FeedbackMessage.sender_role == "user",
                FeedbackMessage.is_read == 0,
            )
        else:
            stmt = (
                select(func.count())
                .select_from(FeedbackMessage)
                .join(Feedback, Feedback.id == FeedbackMessage.feedback_id)
                .where(
                    Feedback.user_id == user_id,
                    FeedbackMessage.sender_role == "admin",
                    FeedbackMessage.is_read == 0,
                )
            )
        return int(db.scalar(stmt) or 0)

    def mark_read_for_user(self, db: Session, feedback: Feedback) -> int:
        """用户已读：把该工单内 ``sender_role='admin'`` 的消息置 ``is_read=1``，返回条数。"""
        result = db.execute(
            update(FeedbackMessage)
            .where(
                FeedbackMessage.feedback_id == feedback.id,
                FeedbackMessage.sender_role == "admin",
                FeedbackMessage.is_read == 0,
            )
            .values(is_read=1)
        )
        db.commit()
        return int(result.rowcount or 0)

    def mark_read_for_admin(self, db: Session, feedback: Feedback) -> int:
        """管理员已读：把该工单内 ``sender_role='user'`` 的消息置 ``is_read=1``，返回条数。"""
        result = db.execute(
            update(FeedbackMessage)
            .where(
                FeedbackMessage.feedback_id == feedback.id,
                FeedbackMessage.sender_role == "user",
                FeedbackMessage.is_read == 0,
            )
            .values(is_read=1)
        )
        db.commit()
        return int(result.rowcount or 0)


# 模块级单例
ticket_service = TicketService()


__all__ = ["TicketService", "ticket_service"]
