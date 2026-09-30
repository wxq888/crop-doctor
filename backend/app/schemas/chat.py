# -*- coding: utf-8 -*-
"""chat 相关请求/响应模型。

契约见 ``docs/impl-rag-chat-v1.md`` §4。时间出参统一经 ``UtcDatetime`` 序列化为
ISO-8601 带 ``Z``（复用 ``schemas/common.py``）。
"""
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class CitationOut(BaseModel):
    """引用来源出参（对应 ``chat_messages.citations`` 元素）。"""

    doc_id: str = Field(description="文档标识（slug）")
    title: str = Field(description="形如「番茄晚疫病·二、症状识别」")
    snippet: str = Field(description="chunk 前 120 字摘要")


class ChatSessionCreate(BaseModel):
    """创建会话入参。"""

    title: str | None = Field(default=None, max_length=100, description="会话标题，可空")
    detection_id: int | None = Field(default=None, description="关联的检测记录 id，可空")


class ChatSessionOut(BaseModel):
    """会话出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    detection_id: int | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class DetectionContextOut(BaseModel):
    """检测上下文卡片数据（复用检测结果，供 H5 顶部卡片渲染）。"""

    detection_id: int
    crop: str | None = Field(default=None, description="作物英文前缀")
    crop_cn: str | None = None
    disease_cn: str | None = None
    class_name: str | None = Field(default=None, description="模型原始类名（逐字）")
    severity_level: int | None = None
    severity_label: str | None = None
    top_conf: float | None = None
    thumb_url: str | None = None


class ChatSessionDetailOut(ChatSessionOut):
    """会话详情出参（在会话基础上追加消息数与检测上下文）。"""

    message_count: int = 0
    detection_context: "DetectionContextOut | None" = None


class ChatMessageOut(BaseModel):
    """消息出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str = Field(description="user | assistant")
    content: str
    citations: list[CitationOut] | None = None
    created_at: UtcDatetime


class ChatMessageIn(BaseModel):
    """向已有会话发送消息入参。

    ``question`` 不加 Pydantic 长度约束：空/纯空白/超长的边界校验统一在 handler 层
    完成，以保证返回 ``400 / 4003``（用户契约，见设计文档 §3.4），而非 422 / 9000。
    """

    question: str


class ChatAskIn(BaseModel):
    """直接提问入参（``session_id`` 为空则自动建会话）。

    ``question`` 同 :class:`ChatMessageIn`，长度/空值校验在 handler 层，返回 400 / 4003。
    """

    question: str
    session_id: int | None = None
    detection_id: int | None = None
    class_name: str | None = Field(default=None, max_length=100, description="可选：直接指定类别过滤")


# 前向引用回填（DetectionContextOut 在 ChatSessionDetailOut 之后定义）
ChatSessionDetailOut.model_rebuild()


__all__ = [
    "CitationOut",
    "ChatSessionCreate",
    "ChatSessionOut",
    "DetectionContextOut",
    "ChatSessionDetailOut",
    "ChatMessageOut",
    "ChatMessageIn",
    "ChatAskIn",
]
