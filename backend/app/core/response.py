# -*- coding: utf-8 -*-
"""统一响应体构造。

约定：所有 HTTP 接口的成功/业务失败响应体均为 ``{code, message, data}``，
``code == 0`` 表示成功。SSE / WebSocket 等文件类接口除外。
"""
from math import ceil
from typing import Any


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    """构造成功响应体。"""
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """构造失败响应体。"""
    return {"code": code, "message": message, "data": data}


def page_data(items: list[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    """构造分页响应体 ``{items,total,page,page_size,pages}``。"""
    pages = ceil(total / page_size) if page_size > 0 else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


__all__ = ["ok", "fail", "page_data"]
