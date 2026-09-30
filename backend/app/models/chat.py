# -*- coding: utf-8 -*-
"""chat_sessions 会话 与 chat_messages 消息。"""
from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin

# 消息角色
CHAT_ROLE_ENUM = Enum("user", "assistant", name="chat_role", native_enum=True)


class ChatSession(Base, TimestampMixin):
    """问诊会话。"""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_chat_user", "user_id"),
        Index("ix_chat_detection", "detection_id"),
        Index("ix_chat_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_chat_sessions_user"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detection_id: Mapped[int | None] = mapped_column(
        ForeignKey("detection_records.id", name="fk_chat_sessions_detection", ondelete="SET NULL"),
        nullable=True,
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ChatMessage(Base, CreatedAtMixin):
    """会话消息。"""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chatmsg_session", "chat_session_id"),
        Index("ix_chatmsg_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", name="fk_chat_messages_session", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(CHAT_ROLE_ENUM, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{doc_id,title,snippet}]
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
