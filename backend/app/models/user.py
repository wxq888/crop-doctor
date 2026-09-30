# -*- coding: utf-8 -*-
"""users 用户表。"""
from sqlalchemy import Enum, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 角色枚举（MySQL 原生 ENUM）
ROLE_ENUM = Enum("user", "admin", name="role", native_enum=True)


class User(Base, TimestampMixin):
    """用户。"""

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_role", "role"),
        Index("ix_users_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str] = mapped_column(ROLE_ENUM, nullable=False, default="user", server_default="user")
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
