# -*- coding: utf-8 -*-
"""通用工具包：时间口径等跨模块共享函数。"""
from datetime import datetime, timezone

__all__ = ["utcnow", "to_iso"]


def utcnow() -> datetime:
    """返回当前 UTC 时间（naive），用于写入 ``DATETIME`` 列。

    项目约定：数据库一律存 UTC，因此落库前去掉 tzinfo 以避免驱动告警。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_iso(dt: datetime | None) -> str | None:
    """把 UTC ``datetime`` 序列化为 ISO-8601 带 ``Z``（如 ``2025-06-01T03:00:00Z``）。

    naive 时间视为 UTC；带 tzinfo 的时间先转换为 UTC。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
