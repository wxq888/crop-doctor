# -*- coding: utf-8 -*-
"""knowledge_docs 知识文档。"""
from sqlalchemy import Enum, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 向量化状态
VECTOR_STATUS_ENUM = Enum("pending", "done", "failed", name="vector_status", native_enum=True)


class KnowledgeDoc(Base, TimestampMixin):
    """知识库文档（门户浏览与 RAG 向量化共用同一数据源）。"""

    __tablename__ = "knowledge_docs"
    __table_args__ = (
        Index("ix_kdoc_crop", "crop"),
        Index("ix_kdoc_disease", "disease"),
        Index("ix_kdoc_vector", "vector_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    crop: Mapped[str | None] = mapped_column(String(50), nullable=True)
    disease: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Markdown 正文（MySQL MEDIUMTEXT）
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    vector_status: Mapped[str] = mapped_column(
        VECTOR_STATUS_ENUM,
        nullable=False,
        default="pending",
        server_default="pending",
    )
