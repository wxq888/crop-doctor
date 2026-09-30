# -*- coding: utf-8 -*-
"""反馈工单（feedback）相关请求/响应模型。

契约见 ``docs/impl-pc-admin-v1.md`` §2.4 / §5。时间出参统一经 ``UtcDatetime``
序列化为 ISO-8601 带 ``Z``。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

FeedbackType = Literal["question", "result_verdict"]
Verdict = Literal["correct", "wrong", "unsure"]
SenderRole = Literal["user", "admin"]


class FeedbackCreate(BaseModel):
    """创建工单入参。"""

    type: FeedbackType = Field(description="question 问题咨询 / result_verdict 检测结果对错标记")
    title: str = Field(max_length=200, description="标题（必填）")
    content: str = Field(description="首条消息正文")
    record_id: int | None = Field(default=None, description="关联检测记录 id（result_verdict 用）")
    verdict: Verdict | None = Field(default=None, description="对错判定（result_verdict 用）")
    correct_disease: str | None = Field(default=None, max_length=100, description="正确的病害名（可选）")


class MessageIn(BaseModel):
    """用户/管理员回复入参。"""

    content: str = Field(description="消息正文")


class FeedbackMessageOut(BaseModel):
    """工单消息出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    feedback_id: int
    sender_role: SenderRole
    sender_id: int
    content: str
    is_read: bool = False
    created_at: UtcDatetime


class FeedbackOut(BaseModel):
    """工单头出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    record_id: int | None = None
    verdict: str | None = None
    correct_disease: str | None = None
    title: str
    status: str
    last_reply_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    message_count: int = 0
    unread_count: int = 0


class FeedbackItem(BaseModel):
    """工单列表项（H5「我的工单」）。"""

    id: int
    type: str
    title: str
    status: str
    record_id: int | None = None
    last_reply_at: UtcDatetime | None = None
    created_at: UtcDatetime
    message_count: int = 0
    unread_count: int = 0


class RecordBrief(BaseModel):
    """``result_verdict`` 工单附带的检测样本摘要。"""

    id: int
    thumb_url: str | None = None
    annotated_url: str | None = None
    top_disease: str | None = None
    disease_cn: str | None = None
    severity_level: int = 0
    severity_label: str | None = None
    top_conf: float | None = None


class FeedbackDetail(FeedbackOut):
    """工单详情出参（含多轮消息与可选的检测样本）。"""

    messages: list[FeedbackMessageOut] = Field(default_factory=list)
    record: RecordBrief | None = None


class AdminFeedbackItem(FeedbackItem):
    """管理端工单列表项（附用户信息与最新消息摘要）。"""

    user_id: int
    username: str | None = None
    nickname: str | None = None
    last_message: str | None = None


class AdminFeedbackDetail(FeedbackDetail):
    """管理端工单详情出参。"""

    username: str | None = None
    nickname: str | None = None


__all__ = [
    "FeedbackType",
    "Verdict",
    "SenderRole",
    "FeedbackCreate",
    "MessageIn",
    "FeedbackMessageOut",
    "FeedbackOut",
    "FeedbackItem",
    "RecordBrief",
    "FeedbackDetail",
    "AdminFeedbackItem",
    "AdminFeedbackDetail",
]
