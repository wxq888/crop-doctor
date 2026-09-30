# -*- coding: utf-8 -*-
"""知识库接口：门户（需登录）+ admin 管理 + 重新向量化。

设计依据：``docs/impl-pc-admin-v1.md`` §2.5 / §6。

**team-lead 裁决**：门户 ``/knowledge/*`` 读端点**需要登录**（不做公开访问，与 H5 其它 Tab 一致），
故门户端点统一挂 ``get_current_user`` 依赖。

扩容友好：作物分类由 ``kb/class-map.json`` + ``knowledge_docs`` 动态聚合，**不写死篇数**；
列表/搜索分页，5 篇 → 38 篇代码零改动。
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin, get_current_user
from app.core.exceptions import (
    CODE_KB_DOC_EXISTS,
    CODE_KB_DOC_NOT_FOUND,
    BusinessError,
)
from app.core.response import ok, page_data
from app.models.knowledge import KnowledgeDoc
from app.models.user import User
from app.schemas.knowledge import (
    AdminKnowledgeItem,
    CropCategoryItem,
    CropCategoryOut,
    DocIn,
    KnowledgeDetail,
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeSearchOut,
    ReindexAcceptedOut,
    ReindexStatusOut,
)
from app.services.knowledge_admin import knowledge_admin_service
from app.utils.classmap import crop_pairs

# 门户路由（前缀 /knowledge）与 admin 路由（前缀 /admin/knowledge）
router = APIRouter()
admin_router = APIRouter()

# 无专属错误码时使用的通用请求错误码（400）
CODE_BAD_REQUEST = 9000


# ============================================================
# 内部工具
# ============================================================
def _snippet(content_md: str, size: int = 120) -> str:
    """正文摘要（去换行，截断）。"""
    text = (content_md or "").replace("\n", " ").replace("\r", " ").strip()
    return text[:size]


def _to_detail(doc: KnowledgeDoc) -> KnowledgeDetail:
    """KnowledgeDoc → 详情出参。"""
    return KnowledgeDetail(
        id=doc.id,
        title=doc.title,
        crop=doc.crop,
        disease=doc.disease,
        source_path=doc.source_path,
        content_md=doc.content_md,
        vector_status=doc.vector_status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _to_item(doc: KnowledgeDoc, *, admin: bool) -> dict:
    """KnowledgeDoc → 列表项载荷。"""
    if admin:
        return AdminKnowledgeItem(
            id=doc.id,
            title=doc.title,
            crop=doc.crop,
            disease=doc.disease,
            snippet=_snippet(doc.content_md),
            vector_status=doc.vector_status,
            updated_at=doc.updated_at,
            source_path=doc.source_path,
        ).model_dump()
    return KnowledgeItem(
        id=doc.id,
        title=doc.title,
        crop=doc.crop,
        disease=doc.disease,
        snippet=_snippet(doc.content_md),
        vector_status=doc.vector_status,
        updated_at=doc.updated_at,
    ).model_dump()


# ============================================================
# 门户（需登录）
# ============================================================
@router.get("/crops", summary="作物分类（动态聚合）")
def list_crops(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """由 class-map 与 knowledge_docs 动态聚合作物分类与病害数（不写死篇数）。"""
    counts = {
        crop: int(cnt)
        for crop, cnt in db.execute(
            select(KnowledgeDoc.crop, func.count()).group_by(KnowledgeDoc.crop)
        ).all()
        if crop
    }
    items: list[CropCategoryItem] = []
    seen: set[str] = set()
    # 先按 class-map 的作物清单（事实来源），再补 knowledge_docs 中出现但映射表未列的作物
    for crop_en, crop_cn in crop_pairs():
        items.append(
            CropCategoryItem(crop_cn=crop_cn, crop_en=crop_en, disease_count=counts.get(crop_cn, 0))
        )
        seen.add(crop_cn)
    for crop_cn, cnt in counts.items():
        if crop_cn not in seen:
            items.append(CropCategoryItem(crop_cn=crop_cn, crop_en=None, disease_count=cnt))
    return ok(CropCategoryOut(items=items))


@router.get("/docs", summary="知识文档列表")
def list_docs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    crop: Annotated[str | None, Query(max_length=50, description="按作物筛选")] = None,
    disease: Annotated[str | None, Query(max_length=100, description="按病害筛选")] = None,
    q: Annotated[str | None, Query(max_length=100, description="标题/正文模糊")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict:
    """分页返回知识文档（门户）。"""
    conditions = []
    if crop:
        conditions.append(KnowledgeDoc.crop == crop)
    if disease:
        conditions.append(KnowledgeDoc.disease == disease)
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(
                KnowledgeDoc.title.like(like),
                KnowledgeDoc.disease.like(like),
                KnowledgeDoc.content_md.like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(KnowledgeDoc).where(*conditions)) or 0
    rows = db.scalars(
        select(KnowledgeDoc)
        .where(*conditions)
        .order_by(KnowledgeDoc.updated_at.desc(), KnowledgeDoc.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_to_item(r, admin=False) for r in rows]
    return ok(page_data(items, int(total), page, page_size))


@router.get("/search", summary="知识检索（语义优先，关键字兜底）")
def search_docs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, max_length=100, description="检索词")],
    top_k: Annotated[int, Query(ge=1, le=20, description="返回条数")] = 4,
) -> dict:
    """优先向量检索（``mode=semantic``），未就绪/无命中时回退 SQL LIKE（``mode=keyword``）。

    **始终返回结果集，绝不抛错**（对齐「降级不抛错」原则）。
    """
    hits = _semantic_search(q, top_k)
    if hits:
        return ok(KnowledgeSearchOut(items=hits, mode="semantic"))
    return ok(KnowledgeSearchOut(items=_keyword_search(db, q, top_k), mode="keyword"))


@router.get("/docs/{doc_id}", summary="知识文档详情")
def get_doc(
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回知识文档详情；不存在 → 404 / 7001。"""
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise BusinessError(CODE_KB_DOC_NOT_FOUND, "知识文档不存在", http_status=404)
    return ok(_to_detail(doc))


def _semantic_search(q: str, top_k: int) -> list[KnowledgeHit]:
    """向量检索（RAG 未就绪一律返回空）。"""
    try:
        from app.services.rag import rag_service  # noqa: PLC0415 —— 惰性导入
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"RAG 服务不可用，检索回退关键字：{exc}")
        return []
    try:
        result = rag_service.search(q, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 —— 检索异常同样降级
        logger.warning(f"向量检索异常，回退关键字：{type(exc).__name__}: {exc}")
        return []
    hits: list[KnowledgeHit] = []
    for chunk in getattr(result, "chunks", []) or []:
        hits.append(
            KnowledgeHit(
                doc_id=getattr(chunk, "doc_db_id", None),
                slug=getattr(chunk, "doc_slug", None),
                title=getattr(chunk, "title", ""),
                section=getattr(chunk, "section", None),
                crop=getattr(chunk, "crop_cn", None),
                disease=getattr(chunk, "title", None),
                snippet=_snippet(getattr(chunk, "text", "")),
                score=float(getattr(chunk, "score", 0.0)),
            )
        )
    return hits


def _keyword_search(db: Session, q: str, top_k: int) -> list[KnowledgeHit]:
    """关键字检索（SQL LIKE 兜底）。"""
    like = f"%{q}%"
    rows = db.scalars(
        select(KnowledgeDoc)
        .where(
            or_(
                KnowledgeDoc.title.like(like),
                KnowledgeDoc.disease.like(like),
                KnowledgeDoc.content_md.like(like),
            )
        )
        .order_by(KnowledgeDoc.updated_at.desc(), KnowledgeDoc.id.desc())
        .limit(top_k)
    ).all()
    return [
        KnowledgeHit(
            doc_id=r.id,
            slug=Path(r.source_path).stem if r.source_path else None,
            title=r.title,
            section=None,
            crop=r.crop,
            disease=r.disease,
            snippet=_snippet(r.content_md),
            score=None,
        )
        for r in rows
    ]


# ============================================================
# admin · 知识库管理
# ============================================================
@admin_router.get("/docs", summary="知识文档列表（管理端）")
def admin_list_docs(
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    crop: Annotated[str | None, Query(max_length=50)] = None,
    disease: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    vector_status: Annotated[str | None, Query(description="pending/done/failed")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict:
    """分页返回知识文档（管理端，多筛选）。"""
    conditions = []
    if crop:
        conditions.append(KnowledgeDoc.crop == crop)
    if disease:
        conditions.append(KnowledgeDoc.disease == disease)
    if vector_status:
        conditions.append(KnowledgeDoc.vector_status == vector_status)
    if q:
        like = f"%{q}%"
        conditions.append(or_(KnowledgeDoc.title.like(like), KnowledgeDoc.content_md.like(like)))
    total = db.scalar(select(func.count()).select_from(KnowledgeDoc).where(*conditions)) or 0
    rows = db.scalars(
        select(KnowledgeDoc)
        .where(*conditions)
        .order_by(KnowledgeDoc.updated_at.desc(), KnowledgeDoc.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_to_item(r, admin=True) for r in rows]
    return ok(page_data(items, int(total), page, page_size))


@admin_router.post("/docs", summary="新建知识文档（md 上传或 JSON）")
async def admin_create_doc(
    request: Request,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """支持 multipart ``file``(.md) 或 JSON ``{title,crop,disease,content_md,slug}``。

    写 ``kb/diseases/<slug>.md`` → upsert ``knowledge_docs``（``vector_status='pending'``）；
    slug 冲突 → 409 / 7002。
    """
    content_type = request.headers.get("content-type", "")
    title: str | None = None
    crop: str | None = None
    disease: str | None = None
    content_md: str | None = None
    slug: str | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise BusinessError(CODE_BAD_REQUEST, "缺少上传文件 file", http_status=400)
        raw = await upload.read()
        if isinstance(raw, bytes):
            content_md = raw.decode("utf-8", errors="replace")
        else:  # pragma: no cover —— 非文件字段兜底
            content_md = str(raw)
        title = (form.get("title") or None) if isinstance(form.get("title"), str) else None
        crop = (form.get("crop") or None) if isinstance(form.get("crop"), str) else None
        disease = (form.get("disease") or None) if isinstance(form.get("disease"), str) else None
        slug = (form.get("slug") or None) if isinstance(form.get("slug"), str) else None
        if not title:
            filename = getattr(upload, "filename", None) or "doc.md"
            title = knowledge_admin_service.parse_title(content_md, Path(filename).stem)
    else:
        body = await request.json()
        if not isinstance(body, dict):
            raise BusinessError(CODE_BAD_REQUEST, "请求体应为 JSON 对象", http_status=400)
        parsed = DocIn(**body)
        title = parsed.title
        crop = parsed.crop
        disease = parsed.disease
        content_md = parsed.content_md
        slug = parsed.slug
        if not content_md or not content_md.strip():
            raise BusinessError(CODE_BAD_REQUEST, "content_md 不能为空", http_status=400)
        if not title:
            title = knowledge_admin_service.parse_title(content_md, "未命名文档")

    if not title or not title.strip():
        title = "未命名文档"
    slug = slug or knowledge_admin_service.slugify(title)
    source_path = knowledge_admin_service.source_path_for(slug)
    if knowledge_admin_service.get_by_source_path(db, source_path) is not None:
        raise BusinessError(CODE_KB_DOC_EXISTS, "知识文档已存在（slug 冲突）", http_status=409)

    knowledge_admin_service.write_md(slug, content_md or "")
    doc = knowledge_admin_service.upsert_doc(
        db,
        source_path=source_path,
        title=title,
        crop=crop,
        disease=disease,
        content_md=content_md or "",
        vector_status="pending",
    )
    return ok(_to_detail(doc))


@admin_router.put("/docs/{doc_id}", summary="更新知识文档")
def admin_update_doc(
    doc_id: int,
    payload: DocIn,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """局部更新文档；正文变更时同步重写 md 文件。不存在 → 404 / 7001。"""
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise BusinessError(CODE_KB_DOC_NOT_FOUND, "知识文档不存在", http_status=404)

    if payload.title is not None:
        doc.title = payload.title
    if payload.crop is not None:
        doc.crop = payload.crop
    if payload.disease is not None:
        doc.disease = payload.disease
    if payload.content_md is not None:
        doc.content_md = payload.content_md
        slug = Path(doc.source_path).stem if doc.source_path else knowledge_admin_service.slugify(doc.title)
        doc.source_path = knowledge_admin_service.write_md(slug, payload.content_md)
    doc.vector_status = "pending"
    db.commit()
    db.refresh(doc)
    return ok(_to_detail(doc))


@admin_router.delete("/docs/{doc_id}", summary="删除知识文档")
def admin_delete_doc(
    doc_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """删除文档行与其 md 文件；不存在 → 404 / 7001。"""
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise BusinessError(CODE_KB_DOC_NOT_FOUND, "知识文档不存在", http_status=404)
    slug = Path(doc.source_path).stem if doc.source_path else knowledge_admin_service.slugify(doc.title)
    knowledge_admin_service.delete_doc(db, doc)
    knowledge_admin_service.delete_md(slug)
    return ok(None)


@admin_router.post("/reindex", summary="触发重新向量化")
def admin_reindex(
    admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """后台触发重建 FAISS 索引（幂等）；返回即时受理状态。"""
    started = knowledge_admin_service.reindex_async()
    status = knowledge_admin_service.reindex_status()
    return ok(ReindexAcceptedOut(accepted=True, running=bool(started) or status["running"]))


@admin_router.get("/reindex/status", summary="重新向量化状态")
def admin_reindex_status(
    admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """返回重建状态 ``{running,last_built_at,count,error}``。"""
    return ok(ReindexStatusOut(**knowledge_admin_service.reindex_status()))


__all__ = ["router", "admin_router"]
