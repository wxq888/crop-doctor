# -*- coding: utf-8 -*-
"""ORM 模型汇总导入。

Alembic autogenerate 与 ``Base.metadata`` 需要在此处把所有模型导入一遍，
否则相关表不会被登记到元数据中。
"""
from app.models.base import Base, CreatedAtMixin, TimestampMixin
from app.models.chat import CHAT_ROLE_ENUM, ChatMessage, ChatSession
from app.models.detection import (
    GRADCAM_STATUS_ENUM,
    DetectionDetail,
    DetectionRecord,
)
from app.models.feedback import (
    FEEDBACK_STATUS_ENUM,
    FEEDBACK_TYPE_ENUM,
    SENDER_ROLE_ENUM,
    VERDICT_ENUM,
    Feedback,
    FeedbackMessage,
)
from app.models.knowledge import VECTOR_STATUS_ENUM, KnowledgeDoc
from app.models.user import ROLE_ENUM, User
from app.models.warning import (
    ALERT_SOURCE_ENUM,
    RAIN_CONDITION_ENUM,
    RISK_LEVEL_ENUM,
    AlertRecord,
    DiseaseWeatherRule,
)

__all__ = [
    "Base",
    "CreatedAtMixin",
    "TimestampMixin",
    "User",
    "ROLE_ENUM",
    "DetectionRecord",
    "DetectionDetail",
    "GRADCAM_STATUS_ENUM",
    "Feedback",
    "FeedbackMessage",
    "FEEDBACK_TYPE_ENUM",
    "FEEDBACK_STATUS_ENUM",
    "VERDICT_ENUM",
    "SENDER_ROLE_ENUM",
    "DiseaseWeatherRule",
    "AlertRecord",
    "RAIN_CONDITION_ENUM",
    "RISK_LEVEL_ENUM",
    "ALERT_SOURCE_ENUM",
    "KnowledgeDoc",
    "VECTOR_STATUS_ENUM",
    "ChatSession",
    "ChatMessage",
    "CHAT_ROLE_ENUM",
]
