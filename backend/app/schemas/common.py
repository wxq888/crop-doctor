# -*- coding: utf-8 -*-
"""通用 Schema：统一响应、分页模型、UTC 时间序列化。

时间口径：数据库存 UTC naive ``datetime``；出参经 ``UtcDatetime`` 序列化为
ISO-8601 带 ``Z``（如 ``2025-06-01T03:00:00Z``）。
"""
from datetime import datetime, timezone
from math import ceil
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

T = TypeVar("T")


def to_utc_z(dt: datetime) -> str:
    """把 ``datetime`` 序列化为 ISO-8601 带 ``Z``（按 UTC）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# 出参专用时间类型：无论 python/json 序列化模式，一律输出带 Z 的字符串
UtcDatetime = Annotated[datetime, PlainSerializer(to_utc_z, return_type=str, when_used="always")]


class Response(BaseModel, Generic[T]):
    """统一响应信封 ``{code, message, data}``。"""

    model_config = ConfigDict(from_attributes=True)

    code: int = Field(default=0, description="业务码，0 = 成功")
    message: str = Field(default="success", description="提示信息")
    data: T | None = Field(default=None, description="业务数据")


class PageQuery(BaseModel):
    """分页入参：``page >= 1``，``1 <= page_size <= 100``。"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=10, ge=1, le=100, description="每页条数，1~100")


class PageData(BaseModel, Generic[T]):
    """分页响应体 ``{items,total,page,page_size,pages}``。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    pages: int = 0

    @classmethod
    def build(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PageData[T]":
        """按 ``total`` 与 ``page_size`` 计算 ``pages`` 并构造实例。"""
        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


__all__ = ["Response", "PageQuery", "PageData", "UtcDatetime", "to_utc_z"]
