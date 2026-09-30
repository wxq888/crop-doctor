# -*- coding: utf-8 -*-
"""ORM 基类再导出与时间戳混入。

时间口径：数据库一律存 **UTC naive** ``datetime``（与序列化层「打 Z」口径一致）。
默认值在 Python 端生成，避免依赖 MySQL 会话时区（历史缺陷：会话时区 +08:00
导致 ``func.now()`` 落库本地墙钟时间，前端再 +8h 显示成明天）。
"""
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.utils import utcnow as _utcnow_naive

__all__ = ["Base", "TimestampMixin", "CreatedAtMixin"]


class TimestampMixin:
    """含 ``created_at`` + ``updated_at`` 的混入（UTC，Python 端默认值）。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow_naive,
        comment="创建时间（UTC）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
        comment="更新时间（UTC）",
    )


class CreatedAtMixin:
    """仅含 ``created_at`` 的混入（UTC）。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow_naive,
        comment="创建时间（UTC）",
    )
