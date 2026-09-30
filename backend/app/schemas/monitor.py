# -*- coding: utf-8 -*-
"""monitor 事件协议 Schema（前后端冻结契约 v1）。

设计依据：``docs/impl-pc-admin-v1.md`` §3.2。

信封（所有事件统一）::

    { "v": 1, "type": "<事件名>", "ts": "2026-09-17T03:00:00Z", "data": { } }

时间 ``ts`` 为 ISO-8601 带 ``Z``（UTC）。``data`` 仅含**非敏感摘要**。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MonitorEvent(BaseModel):
    """WS 事件帧（模型化描述，运行时以 dict 直接下发，避免序列化开销）。"""

    model_config = ConfigDict(from_attributes=True)

    v: int = Field(default=1, description="协议版本")
    type: str = Field(description="事件名，如 detection.created")
    ts: str = Field(description="事件时间（ISO-8601 带 Z）")
    data: dict[str, Any] = Field(default_factory=dict, description="事件负载（非敏感摘要）")


class MonitorEventsOut(BaseModel):
    """``GET /admin/monitor/events`` 出参：最近事件快照。"""

    items: list[MonitorEvent] = Field(default_factory=list)


class DetectionCreatedPayload(BaseModel):
    """``detection.created`` 事件负载。"""

    record_id: int
    user_id: int
    username: str | None = None
    nickname: str | None = None
    top_disease: str | None = None
    disease_cn: str | None = None
    crop: str | None = None
    crop_cn: str | None = None
    severity_level: int = 0
    severity_label: str = "未知"
    top_conf: float | None = None
    thumb_url: str | None = None
    created_at: str | None = None


class FeedbackCreatedPayload(BaseModel):
    """``feedback.created`` 事件负载（新建工单 / 用户追问）。"""

    feedback_id: int
    type: str
    title: str
    user_id: int
    username: str | None = None
    record_id: int | None = None
    status: str
    created_at: str | None = None


class FeedbackRepliedPayload(BaseModel):
    """``feedback.replied`` 事件负载（管理员回复）。"""

    feedback_id: int
    admin_id: int
    admin_name: str | None = None
    to_user_id: int
    title: str
    replied_at: str | None = None


class WarningCreatedPayload(BaseModel):
    """``warning.created`` 事件负载（新增预警记录）。"""

    alert_id: int
    source: str
    disease: str
    disease_cn: str | None = None
    risk_level: str
    location: str | None = None
    forecast_date: str | None = None
    content: str
    created_at: str | None = None


class HelloPayload(BaseModel):
    """``hello`` 事件负载（握手成功首帧）。"""

    server: str = "cropdoctor"
    heartbeat_seconds: int = 25
    recent: list[MonitorEvent] = Field(default_factory=list)


__all__ = [
    "MonitorEvent",
    "MonitorEventsOut",
    "DetectionCreatedPayload",
    "FeedbackCreatedPayload",
    "FeedbackRepliedPayload",
    "WarningCreatedPayload",
    "HelloPayload",
]
