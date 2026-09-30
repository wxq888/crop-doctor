# -*- coding: utf-8 -*-
"""知识库（knowledge）相关请求/响应模型。

契约见 ``docs/impl-pc-admin-v1.md`` §2.5 / §6。时间出参统一经 ``UtcDatetime``
序列化为 ISO-8601 带 ``Z``。
"""
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class CropCategoryItem(BaseModel):
    """门户作物分类项。"""

    crop_cn: str
    crop_en: str | None = None
    disease_count: int = 0


class CropCategoryOut(BaseModel):
    """门户作物分类出参。"""

    items: list[CropCategoryItem] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    """知识文档列表项。"""

    id: int
    title: str
    crop: str | None = None
    disease: str | None = None
    snippet: str | None = Field(default=None, description="正文前若干字摘要")
    vector_status: str | None = None
    updated_at: UtcDatetime


class KnowledgeDetail(BaseModel):
    """知识文档详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    crop: str | None = None
    disease: str | None = None
    source_path: str | None = None
    content_md: str
    vector_status: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AdminKnowledgeItem(KnowledgeItem):
    """管理端知识文档列表项（附来源路径）。"""

    source_path: str | None = None


class KnowledgeHit(BaseModel):
    """门户检索命中项。"""

    doc_id: int | None = None
    slug: str | None = None
    title: str
    section: str | None = None
    crop: str | None = None
    disease: str | None = None
    snippet: str | None = None
    score: float | None = None


class KnowledgeSearchOut(BaseModel):
    """门户检索出参（``mode`` 标识语义/关键字）。"""

    items: list[KnowledgeHit] = Field(default_factory=list)
    mode: str = Field(default="keyword", description="semantic | keyword")


class DocIn(BaseModel):
    """管理端新建/更新知识文档入参（JSON 模式）。"""

    title: str | None = Field(default=None, max_length=200)
    crop: str | None = Field(default=None, max_length=50)
    disease: str | None = Field(default=None, max_length=100)
    content_md: str | None = None
    slug: str | None = Field(default=None, max_length=120, description="文件名主体，缺省由标题派生")


class ReindexAcceptedOut(BaseModel):
    """触发重新向量化的即时响应。"""

    accepted: bool = True
    running: bool = False


class ReindexStatusOut(BaseModel):
    """重新向量化状态。"""

    running: bool = False
    last_built_at: str | None = None
    count: int = 0
    error: str | None = None


__all__ = [
    "CropCategoryItem",
    "CropCategoryOut",
    "KnowledgeItem",
    "KnowledgeDetail",
    "AdminKnowledgeItem",
    "KnowledgeHit",
    "KnowledgeSearchOut",
    "DocIn",
    "ReindexAcceptedOut",
    "ReindexStatusOut",
]
