# -*- coding: utf-8 -*-
"""feedbacks 反馈工单（头）与 feedback_messages 工单消息（多轮往来）。"""
from datetime import datetime

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin

# 工单类型：问题咨询 / 检测结果对错标记
FEEDBACK_TYPE_ENUM = Enum("question", "result_verdict", name="feedback_type", native_enum=True)
# 工单状态机
FEEDBACK_STATUS_ENUM = Enum("pending", "replied", "closed", name="feedback_status", native_enum=True)
# 对错判定
VERDICT_ENUM = Enum("correct", "wrong", "unsure", name="verdict", native_enum=True)
# 消息发送方角色
SENDER_ROLE_ENUM = Enum("user", "admin", name="sender_role", native_enum=True)


class Feedback(Base, TimestampMixin):
    """反馈工单头。"""

    __tablename__ = "feedbacks"
    __table_args__ = (
        Index("ix_feedback_user", "user_id"),
        Index("ix_feedback_type", "type"),
        Index("ix_feedback_record", "record_id"),
        Index("ix_feedback_status", "status"),
        Index("ix_feedback_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_feedbacks_user"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(FEEDBACK_TYPE_ENUM, nullable=False)
    record_id: Mapped[int | None] = mapped_column(
        ForeignKey("detection_records.id", name="fk_feedbacks_record", ondelete="SET NULL"),
        nullable=True,
    )
    verdict: Mapped[str | None] = mapped_column(VERDICT_ENUM, nullable=True)
    correct_disease: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        FEEDBACK_STATUS_ENUM,
        nullable=False,
        default="pending",
        server_default="pending",
    )
    last_reply_at: Mapped[datetime | None] = mapped_column(nullable=True)

    messages: Mapped[list["FeedbackMessage"]] = relationship(
        back_populates="feedback",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FeedbackMessage(Base, CreatedAtMixin):
    """工单消息（用户与管理员多轮往来）。"""

    __tablename__ = "feedback_messages"
    __table_args__ = (
        Index("ix_fbmsg_feedback", "feedback_id"),
        Index("ix_fbmsg_read", "is_read"),
        Index("ix_fbmsg_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("feedbacks.id", name="fk_feedback_messages_feedback", ondelete="CASCADE"),
        nullable=False,
    )
    sender_role: Mapped[str] = mapped_column(SENDER_ROLE_ENUM, nullable=False)
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_feedback_messages_sender"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")

    feedback: Mapped[Feedback] = relationship(back_populates="messages")
