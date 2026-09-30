# -*- coding: utf-8 -*-
"""chat 问诊接口：会话 CRUD + 消息 + SSE 流式问答（RAG + DeepSeek）+ 检测上下文注入。

设计依据：``docs/impl-rag-chat-v1.md`` §2 / §3 / §5。

数据隔离红线：本模块所有会话/消息查询在 SQL 层强制 ``user_id == current_user.id``；
越权访问统一返回 4001 / 404（不区分"不存在"与"无权"，防探测，对齐 detection 模块策略）。

SSE 事件契约（前后端冻结，见设计文档 §3.2）：
``meta → delta… → done|error``；心跳注释帧 ``: ping``（每 15s）。
- ``meta`` 必为第一帧，携带 ``session_id`` / ``user_message_id`` / ``citations`` / ``degraded`` /
  ``class_filter`` / ``kb_scope_miss``（向后兼容新增，见 team-lead 裁决）；
- ``delta`` 可 0..N 帧，携带增量文本 ``{"text": ...}``；
- ``done`` 或 ``error`` 必为最后一帧。

降级不抛错（对齐设计文档 §2.3 / §12.3）：未配 ``DEEPSEEK_API_KEY``、空知识库、LLM 不可用、
**接口限流 429**、**模型未返回任何 content** 一律 HTTP 200 + 正常 SSE 流，``degraded=true``，
服务不得 500；限流时降级回答直接给出「请求过于频繁」提示。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import (
    CODE_BAD_QUESTION,
    CODE_CHAT_SESSION_NOT_FOUND,
    CODE_INTERNAL,
    CODE_LLM_UNAVAILABLE,
    BusinessError,
)
from app.core.response import ok, page_data
from app.models.chat import ChatMessage, ChatSession
from app.models.detection import DetectionRecord
from app.models.user import User
from app.schemas.chat import (
    ChatAskIn,
    ChatMessageIn,
    ChatMessageOut,
    ChatSessionCreate,
    ChatSessionDetailOut,
    ChatSessionOut,
    DetectionContextOut,
)
from app.services import severity
from app.services.llm import LLMStreamError, LLMUnavailableError, llm_service
from app.utils import storage
from app.utils import utcnow

router = APIRouter()

# ============================================================
# 常量与提示词（设计文档 §5）
# ============================================================
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 关闭 Nginx 等反向代理的缓冲，保证逐字下发
    "X-Accel-Buffering": "no",
}
_PING_FRAME = ": ping\n\n"
_HEARTBEAT_SECONDS = 15.0

SYSTEM_PROMPT = (
    "你是「作物医生」的植保问答助手，面向普通农户，用简体中文回答。\n"
    "\n"
    "【硬性约束】\n"
    "1. 先判断用户问题的类型：\n"
    "   - 与农作物病虫害、种植管理相关的问题：只依据下方【参考资料】回答；参考资料未覆盖的内容，"
    "如实说明「知识库暂无相关权威资料，建议咨询当地植保站」，并可补充一般性种植常识，"
    "但严禁编造农药名称、剂量、安全间隔期。\n"
    "   - 与植保无关的一般问题（问候、闲聊、简单常识、数学等）：正常自然回答，"
    "不受【参考资料】限制，也无需标注引用编号。\n"
    "2. 严禁编造农药名称、剂量、安全间隔期；凡涉及药剂，必须来自参考资料，并提示「严格按农药标签使用、遵守安全间隔期」。\n"
    "3. 病毒病不得推荐杀菌剂（防治以防控传播媒介、抗病品种、拔除病株为主）。\n"
    "4. 检疫性病害（如柑橘黄龙病）不得推荐治疗药剂（防治以防控媒介、清除病株、苗木检疫为主）。\n"
    "5. 虫害（如叶螨）应使用杀螨剂逻辑，并提示轮换用药防抗性。\n"
    "6. 植保相关回答分点、简洁，正文不超过 300 字，结尾用 [1][2] 标注所引用的参考资料编号；一般问题正常回答即可。\n"
    "7. 语气亲切、通俗，避免堆砌专业术语；必要时给出一句农事操作建议。"
)

# 未配 LLM 且检索无命中时的固定提示（设计文档 §2.3）
DEGRADED_NO_HITS_TEXT = (
    "当前未配置大模型问答服务（DEEPSEEK_API_KEY 为空）。"
    "您可先查阅知识库，或联系当地植保站咨询；"
    "如需开启智能问答，请在 .env 配置 DEEPSEEK_API_KEY。"
)
# 未配 LLM 但检索有命中时的抬头（正文为知识库原文，逐字来自检索结果）
DEGRADED_WITH_HITS_HEADER = "【大模型服务未配置，以下为知识库检索原文】\n"


def _ctx_limit() -> int:
    """携带历史消息条数；键缺失时回退默认 8（A 负责落 config 键）。"""
    try:
        return int(getattr(settings, "chat_context_messages", 8))
    except (TypeError, ValueError):
        return 8


def _class_map_path() -> Path:
    """``kb/class-map.json`` 的绝对路径（相对路径以仓库根为基准）。"""
    rel = getattr(settings, "kb_class_map_path", "kb/class-map.json") or "kb/class-map.json"
    path = Path(rel)
    return path if path.is_absolute() else (REPO_ROOT / path)


@lru_cache(maxsize=1)
def _class_map_index() -> dict[str, dict]:
    """加载 ``kb/class-map.json`` → ``{class_name: row}``（内存缓存）。

    文件缺失 / 损坏一律返回空字典（降级为直接用原始类名），绝不抛错。
    """
    path = _class_map_path()
    if not path.exists():
        logger.warning(f"class-map 不存在，检测上下文降级为原始类名：{path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"class-map 解析失败，检测上下文降级为原始类名：{exc}")
        return {}

    index: dict[str, dict] = {}
    for row in raw:
        if isinstance(row, dict) and row.get("class_name"):
            index[str(row["class_name"])] = row
    return index


# ============================================================
# 检索 / 分块视图
# ============================================================
def _load_rag():
    """惰性导入 RAG 服务（归工程师 A）。

    rag 模块未落地 / 导入失败时返回 ``None``，调用方按「空检索」降级处理。
    惰性导入同时避免在服务启动时引入 sentence-transformers / faiss 的重量级导入。
    """
    try:
        from app.services.rag import rag_service  # noqa: PLC0415 —— 惰性导入

        return rag_service
    except Exception as exc:  # noqa: BLE001 —— 任何缺失/异常都降级为空检索
        logger.warning(f"RAG 服务不可用，降级为空检索：{exc}")
        return None


@dataclass
class _Retrieval:
    """检索结果统一封装（兼容 A 的新 ``SearchResult`` 契约与旧 ``list`` 返回值）。"""

    chunks: list = field(default_factory=list)
    scope_miss: bool = False
    crop_scope: str | None = None


def _crop_of_class(class_name: str | None) -> str | None:
    """由模型类名派生**作物名**（用于 RAG 作物范围过滤）。

    优先取 ``kb/class-map.json`` 的 ``crop_cn``（与索引 chunk 的 ``crop_cn`` 字段一致），
    缺失时回退到类名前缀（如 ``Tomato___Late_blight`` → ``Tomato``）。
    """
    if not class_name:
        return None
    crop_cn = _class_map_index().get(class_name, {}).get("crop_cn")
    if crop_cn:
        return crop_cn
    if "___" in class_name:
        return class_name.split("___")[0]
    return class_name.split("_")[0] if "_" in class_name else class_name


def _invoke_search(rag, query: str, crop: str | None, class_name: str | None):
    """调用 A 的检索接口。

    优先**新契约** ``search(query, crop=...)``；并行窗口内（A 尚未落地）回退**旧契约**
    ``search(query, class_name=...)``，避免互相阻塞。
    """
    try:
        return rag.search(query, crop=crop)
    except TypeError:
        return rag.search(query, class_name=class_name)


def _retrieve(query: str, crop: str | None, class_filter: str | None) -> _Retrieval:
    """调用 RAG 检索并统一为 :class:`_Retrieval`；未就绪 / 异常一律降级为空结果（不抛错）。

    ``chunks`` 用 ``getattr(res, "chunks", res)`` 兜住新/旧两种返回形态；
    ``scope_miss`` / ``crop_scope`` 为新增字段，旧实现下取默认值。
    """
    rag = _load_rag()
    if rag is None:
        return _Retrieval()
    try:
        res = _invoke_search(rag, query, crop, class_filter or None)
    except Exception as exc:  # noqa: BLE001 —— 检索失败降级为空，保证对话可用
        logger.warning(f"RAG 检索异常，降级为空检索：{exc}")
        return _Retrieval()

    chunks = list(getattr(res, "chunks", res) or [])
    scope_miss = bool(getattr(res, "scope_miss", False))
    crop_scope = getattr(res, "crop_scope", None)
    if not chunks and not scope_miss:
        logger.warning("RAG 检索无命中（空索引或低于阈值）")
    return _Retrieval(chunks=chunks, scope_miss=scope_miss, crop_scope=crop_scope)


def _chunk_view(chunk) -> dict:
    """把 ``RetrievedChunk`` 规整为提示词/降级文案所需的普通字典。"""
    return {
        "doc_slug": getattr(chunk, "doc_slug", "") or "",
        "title": getattr(chunk, "title", "") or "",
        "class_name": getattr(chunk, "class_name", None),
        "crop_cn": getattr(chunk, "crop_cn", None),
        "category": getattr(chunk, "category", None),
        "section": getattr(chunk, "section", "") or "",
        "text": getattr(chunk, "text", "") or "",
    }


def _citation_of(chunk) -> dict:
    """构造 ``{doc_id,title,snippet}`` 引用（优先用 ``RetrievedChunk.to_citation()``）。"""
    to_citation = getattr(chunk, "to_citation", None)
    if callable(to_citation):
        try:
            return dict(to_citation())
        except Exception as exc:  # noqa: BLE001 —— 契约实现异常时回退自建
            logger.warning(f"to_citation 调用失败，回退自建引用：{exc}")
    view = _chunk_view(chunk)
    title = view["title"]
    section = view["section"]
    combined = f"{title}·{section}" if section else title
    return {
        "doc_id": view["doc_slug"],
        "title": combined,
        "snippet": view["text"][:120].replace("\n", " "),
    }


# ============================================================
# 检测上下文
# ============================================================
def _get_owned_detection(db: Session, detection_id: int, user_id: int) -> DetectionRecord:
    """按 ``id + user_id`` 取检测记录；不存在或非本人一律抛 4001 / 404。"""
    record = db.scalar(
        select(DetectionRecord).where(
            DetectionRecord.id == detection_id,
            DetectionRecord.user_id == user_id,
        )
    )
    if record is None:
        raise BusinessError(CODE_CHAT_SESSION_NOT_FOUND, "检测记录不存在或无权访问", http_status=404)
    return record


def _build_detection_context(record: DetectionRecord) -> DetectionContextOut:
    """由检测记录 + ``class-map.json`` 反查中文名，组装检测上下文卡片数据。"""
    row = _class_map_index().get(record.top_disease or "", {})
    return DetectionContextOut(
        detection_id=record.id,
        crop=record.crop,
        crop_cn=row.get("crop_cn") or record.crop,
        disease_cn=row.get("disease_cn") or record.top_disease,
        class_name=record.top_disease,
        severity_level=record.severity_level,
        severity_label=severity.label_of(record.severity_level),
        top_conf=record.top_conf,
        thumb_url=storage.url_of(record.image_path),
    )


# ============================================================
# 会话 / 消息辅助
# ============================================================
def _get_owned_session(db: Session, session_id: int, user_id: int) -> ChatSession:
    """按 ``id + user_id`` 取会话；不存在或非本人一律抛 4001 / 404（防探测）。"""
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    )
    if session is None:
        raise BusinessError(CODE_CHAT_SESSION_NOT_FOUND, "会话不存在或无权访问", http_status=404)
    return session


def _history_messages(db: Session, session_id: int, limit: int) -> list[dict]:
    """取最近 ``limit`` 条历史消息（时间正序），用于注入 LLM 对话上下文。"""
    if limit <= 0:
        return []
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    ).all()
    ordered = list(reversed(rows))
    return [{"role": m.role, "content": m.content} for m in ordered]


def _touch_session(db: Session, session: ChatSession) -> None:
    """刷新会话 ``updated_at``（会话列表按最近活跃排序）。

    使用 Python 端 UTC 时间而非 ``func.now()``：项目约定 DB 存 UTC naive，
    避免依赖数据库会话时区。
    """
    session.updated_at = utcnow()


def _persist_assistant(
    db: Session,
    session: ChatSession,
    content: str,
    citations: list[dict],
) -> ChatMessage:
    """落库 assistant 消息（含引用），并刷新会话活跃时间。"""
    message = ChatMessage(
        chat_session_id=session.id,
        role="assistant",
        content=content or "",
        citations=citations or None,
    )
    db.add(message)
    _touch_session(db, session)
    db.commit()
    db.refresh(message)
    return message


# ============================================================
# 提示词组装（设计文档 §5.2）
# ============================================================
def _build_user_prompt(
    question: str,
    views: list[dict],
    detection_ctx: DetectionContextOut | None,
) -> str:
    """组装注入检测上下文 + 参考资料的 user 提示词。"""
    blocks: list[str] = []
    if detection_ctx is not None:
        conf = f"{detection_ctx.top_conf:.0%}" if detection_ctx.top_conf is not None else "未知"
        blocks.append(
            "【检测上下文】\n"
            f"作物：{detection_ctx.crop_cn or '未知'}｜检测结论：{detection_ctx.disease_cn or '未知'}｜"
            f"置信度：{conf}｜严重度：{detection_ctx.severity_label or '未知'}\n"
            "（说明：以上为用户上传图片的 AI 检测结果，可作为参考，但最终以实际情况为准。）"
        )
    if views:
        ref_lines: list[str] = []
        for idx, view in enumerate(views, start=1):
            ref_lines.append(f"[{idx}] {view['title']}（{view['section']}）\n{view['text']}")
        blocks.append("【参考资料】\n" + "\n\n".join(ref_lines))
    else:
        blocks.append("【参考资料】\n（无）")
    blocks.append(f"【用户问题】\n{question}")
    return "\n\n".join(blocks)


def _compose_messages(
    history: list[dict],
    question: str,
    views: list[dict],
    detection_ctx: DetectionContextOut | None,
) -> list[dict]:
    """组装送往 LLM 的完整消息列表：system + 历史 + 本轮 user。"""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": _build_user_prompt(question, views, detection_ctx)})
    return messages


# ============================================================
# 降级文案（未配 LLM / LLM 不可用）
# ============================================================
def _degraded_text(
    views: list[dict],
    detection_ctx: DetectionContextOut | None,
    scope_miss: bool = False,
    crop_scope: str | None = None,
) -> str:
    """组装降级回答：检测上下文摘要 + 知识库原文（或固定提示 / 库外提示）。

    - ``scope_miss=True``：请求作物在知识库中无任何文档 → 明确告知「知识库暂无【作物】资料」，
      **不再吐别的作物资料**（避免误导）。
    - 有命中：正文按序号引用**全部**命中，与 ``meta.citations`` 一一对应（保证前后端一致）。
    - 无命中：固定提示。

    额外前置一行「检测结果」摘要，使「带 detection_id 的降级回答」也能体现检测上下文
    （对齐验收标准；当 class-map 缺失时中文名回退为原始类名）。
    """
    head = ""
    if detection_ctx is not None:
        conf = f"{detection_ctx.top_conf:.0%}" if detection_ctx.top_conf is not None else "未知"
        head = (
            f"【检测结果】作物：{detection_ctx.crop_cn or '未知'}｜结论：{detection_ctx.disease_cn or '未知'}｜"
            f"置信度：{conf}｜严重度：{detection_ctx.severity_label or '未知'}\n\n"
        )

    if scope_miss:
        crop_name = crop_scope or (detection_ctx.crop_cn if detection_ctx is not None else None) or "该作物"
        return head + (
            f"知识库暂无【{crop_name}】的病害资料，暂无法提供针对性防治建议；"
            "建议补充该作物资料或咨询当地植保站。"
        )

    if not views:
        return head + DEGRADED_NO_HITS_TEXT

    parts = [DEGRADED_WITH_HITS_HEADER]
    for idx, view in enumerate(views, start=1):  # 全部命中，与 meta.citations 保持一致
        parts.append(f"\n[{idx}] {view['title']}（{view['section']}）\n{view['text']}")
    return head + "".join(parts)


# ============================================================
# SSE 底层工具
# ============================================================
def _sse_frame(event: str, data: dict) -> str:
    """构造一帧 SSE（``event:`` + 单行 ``data:`` JSON）。JSON 会转义换行，保证单行。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _emit_text(text: str, chunk_size: int = 24) -> AsyncIterator[str]:
    """把一段文本切分为若干 ``delta`` 帧流式吐出（用于降级文案）。"""
    for i in range(0, len(text), chunk_size):
        yield _sse_frame("delta", {"text": text[i : i + chunk_size]})
        await asyncio.sleep(0)  # 让出事件循环，保证逐帧下发


async def _iter_with_ping(
    token_gen: AsyncIterator[str],
    request: Request,
    interval: float = _HEARTBEAT_SECONDS,
) -> AsyncIterator[tuple[str, str | None]]:
    """把 token 异步迭代器包成带心跳、可感知断连的迭代器。

    Yields:
        ``("delta", text)`` 或 ``("ping", None)``。

    异常由内层任务 `raise` 传出（如 ``LLMStreamError``），交给调用方处理。
    """
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    end_marker = object()

    async def _pump() -> None:
        """后台消费 token 生成器，把结果投递到队列。"""
        try:
            async for token in token_gen:
                await queue.put(("delta", token))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 把异常传给消费端统一处理
            await queue.put(("exc", exc))
            await queue.put(("end", end_marker))
        else:
            await queue.put(("end", end_marker))

    task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                # 空闲超过 interval：先探活，仍在线则发心跳
                if await request.is_disconnected():
                    break
                yield ("ping", None)
                continue
            if kind == "end":
                break
            if kind == "exc":
                raise payload  # type: ignore[misc]
            yield ("delta", payload)  # type: ignore[arg-type]
            if await request.is_disconnected():
                break
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(BaseException):
            await task


# ============================================================
# SSE 主生成器
# ============================================================
async def _sse_generate(
    *,
    request: Request,
    db: Session,
    session: ChatSession,
    user_msg_id: int,
    views: list[dict],
    citations: list[dict],
    messages: list[dict],
    detection_ctx: DetectionContextOut | None,
    class_filter: str | None,
    scope_miss: bool = False,
    crop_scope: str | None = None,
    llm_configured: bool,
) -> AsyncIterator[str]:
    """SSE 问答主流程：``meta → delta… → done|error``（含心跳与降级）。"""
    try:
        # 1) meta 必为第一帧（kb_scope_miss / crop_scope 为向后兼容新增字段，见设计文档 §3.2 v1.1）
        yield _sse_frame(
            "meta",
            {
                "session_id": session.id,
                "user_message_id": user_msg_id,
                "citations": citations,
                "degraded": (not llm_configured),
                "class_filter": class_filter,
                "kb_scope_miss": scope_miss,
                # 回显本次检索生效的作物范围（用户只打病害名、未带作物时为 None）；
                # 旧版 RAG 未返回该字段时由 _retrieve 的 getattr(res, "crop_scope", None) 兜为 None。
                "crop_scope": crop_scope,
            },
        )

        started = time.monotonic()
        full_text = ""

        # 2a) 未配置 LLM：直接走「知识库原文 / 固定提示 / 库外提示」降级，不建立大模型连接
        if not llm_configured:
            degraded = _degraded_text(views, detection_ctx, scope_miss, crop_scope)
            async for frame in _emit_text(degraded):
                yield frame
            full_text = degraded
            _persist_assistant(db, session, full_text, citations)
            yield _sse_frame(
                "error",
                {
                    "code": CODE_LLM_UNAVAILABLE,
                    "message": "大模型服务未配置，已返回知识库原文",
                    "degraded": True,
                },
            )
            return

        # 2b) 已配置 LLM：正常流式
        extra = ""
        err_msg = "大模型服务暂不可用，已返回知识库原文"
        try:
            token_gen = llm_service.stream_chat(messages)
            async for kind, payload in _iter_with_ping(token_gen, request):
                if kind == "ping":
                    yield _PING_FRAME
                    continue
                full_text += payload or ""
                yield _sse_frame("delta", {"text": payload or ""})

            # 约束 2 防御：流式结束却一帧 content 都没有（如 reasoning_content 吃光 token、
            # 或模型不支持 thinking 参数被静默忽略）→ 绝不静默吐空，转降级并给出明确原因。
            if not full_text.strip():
                logger.warning("LLM 流式结束但未产出任何 content，转降级并给出明确原因")
                extra = _degraded_text(views, detection_ctx, scope_miss, crop_scope)
                err_msg = (
                    "大模型未返回任何回答内容（可能未支持 thinking 参数，或返回全为思考内容），"
                    "已降级为知识库原文"
                )
            else:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                assistant = _persist_assistant(db, session, full_text, citations)
                yield _sse_frame(
                    "done",
                    {
                        "assistant_message_id": assistant.id,
                        "finish_reason": "stop",
                        "elapsed_ms": elapsed_ms,
                    },
                )
                return
        except LLMUnavailableError as exc:
            # 含 429 限流（LLMRateLimitError）：优先用其用户友好文案
            reason = getattr(exc, "user_message", None)
            logger.warning(f"LLM 不可用，降级：{exc}")
            if reason:
                # 限流等：降级回答即用户提示，不再拼 KB 原文（避免与「请稍后再试」语义冲突）
                extra = reason
                err_msg = reason
            else:
                extra = _degraded_text(views, detection_ctx, scope_miss, crop_scope)
                err_msg = "大模型服务暂不可用，已返回知识库原文"
        except LLMStreamError as exc:
            logger.error(f"LLM 流式中断，保留已产出文本：{exc}")
            extra = _degraded_text(views, detection_ctx, scope_miss, crop_scope)
            err_msg = "大模型服务中断，已保留已生成内容"

        # 3) 降级 / 中断兜底：已产出部分保留，不足部分用检索原文补齐
        if full_text:
            full_text = f"{full_text}\n\n{extra}"
            async for frame in _emit_text(f"\n\n{extra}"):
                yield frame
        else:
            full_text = extra
            async for frame in _emit_text(extra):
                yield frame
        _persist_assistant(db, session, full_text, citations)
        yield _sse_frame(
            "error",
            {"code": CODE_LLM_UNAVAILABLE, "message": err_msg, "degraded": True},
        )
    except Exception:  # noqa: BLE001 —— 兜底：绝不让 SSE 裸崩，最后推 error 帧
        logger.exception("SSE 流式问答异常")
        yield _sse_frame(
            "error",
            {"code": CODE_INTERNAL, "message": "服务内部错误", "degraded": False},
        )


def _prepare_and_stream(
    *,
    request: Request,
    db: Session,
    session: ChatSession,
    question: str,
    detection_ctx: DetectionContextOut | None,
    class_filter: str | None,
    crop: str | None = None,
) -> StreamingResponse:
    """落库 user 消息 → 检索 → 组装提示词 → 返回 SSE 流式响应。

    注意：本函数（含检索）在返回 ``StreamingResponse`` **之前**执行，故问题为空的场景
    已在调用方 ``_validate_question`` 处抛 400 / 4003（普通 JSON），不会进入 SSE。
    """
    # 1) 先取历史（须在插入本轮 user 消息之前）
    history = _history_messages(db, session.id, _ctx_limit())

    # 2) 落库 user 消息（建立流之前），并刷新会话活跃时间 / 标题
    user_msg = ChatMessage(chat_session_id=session.id, role="user", content=question, citations=None)
    db.add(user_msg)
    if not session.title:
        session.title = question[:100]
    _touch_session(db, session)
    db.commit()
    db.refresh(user_msg)

    # 3) 检索（meta 需要 citations；空索引返回空）
    retrieval = _retrieve(question, crop, class_filter)
    views = [_chunk_view(c) for c in retrieval.chunks]
    citations = [_citation_of(c) for c in retrieval.chunks]

    # 4) 组装提示词
    messages = _compose_messages(history, question, views, detection_ctx)

    generator = _sse_generate(
        request=request,
        db=db,
        session=session,
        user_msg_id=user_msg.id,
        views=views,
        citations=citations,
        messages=messages,
        detection_ctx=detection_ctx,
        class_filter=class_filter,
        scope_miss=retrieval.scope_miss,
        crop_scope=retrieval.crop_scope,
        llm_configured=bool(llm_service.is_configured),
    )
    return StreamingResponse(generator, media_type="text/event-stream", headers=SSE_HEADERS)


def _validate_question(question: str) -> str:
    """校验并规整问题文本；空/纯空白/超长一律 4003。"""
    normalized = (question or "").strip()
    if not normalized or len(normalized) > 500:
        raise BusinessError(CODE_BAD_QUESTION, "问题不能为空且不超过 500 字", http_status=400)
    return normalized


# ============================================================
# 端点：会话 CRUD
# ============================================================
@router.post("/sessions", summary="创建会话")
def create_session(
    payload: ChatSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """新建会话；若带 ``detection_id`` 先校验该检测记录归属（越权 → 4001）。"""
    if payload.detection_id is not None:
        _get_owned_detection(db, payload.detection_id, current_user.id)

    session = ChatSession(
        user_id=current_user.id,
        title=payload.title,
        detection_id=payload.detection_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ok(ChatSessionOut.model_validate(session))


@router.get("/sessions", summary="我的会话列表")
def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 10,
) -> dict:
    """分页返回当前用户本人的会话（强制 user_id 过滤，按最近活跃倒序）。"""
    conditions = [ChatSession.user_id == current_user.id]
    total = db.scalar(select(func.count()).select_from(ChatSession).where(*conditions)) or 0
    rows = db.scalars(
        select(ChatSession)
        .where(*conditions)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [ChatSessionOut.model_validate(row).model_dump() for row in rows]
    return ok(page_data(items, int(total), page, page_size))


@router.get("/sessions/{session_id}", summary="会话详情")
def get_session_detail(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回本人某会话详情（含消息数与检测上下文，越权 → 404 / 4001）。"""
    session = _get_owned_session(db, session_id, current_user.id)
    message_count = (
        db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.chat_session_id == session.id)
        )
        or 0
    )

    out = ChatSessionDetailOut(
        id=session.id,
        title=session.title,
        detection_id=session.detection_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=int(message_count),
        detection_context=None,
    )

    # 检测上下文：仅当关联检测记录仍属于本人时返回（记录已删则 detection_id 会被 SET NULL）
    if session.detection_id is not None:
        record = db.scalar(
            select(DetectionRecord).where(
                DetectionRecord.id == session.detection_id,
                DetectionRecord.user_id == current_user.id,
            )
        )
        if record is not None:
            out.detection_context = _build_detection_context(record)
    return ok(out)


@router.get("/sessions/{session_id}/messages", summary="会话消息列表")
def list_messages(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 10,
) -> dict:
    """分页返回本人某会话的消息（按时间倒序，前端可反转为正序渲染）。"""
    session = _get_owned_session(db, session_id, current_user.id)
    conditions = [ChatMessage.chat_session_id == session.id]
    total = db.scalar(select(func.count()).select_from(ChatMessage).where(*conditions)) or 0
    rows = db.scalars(
        select(ChatMessage)
        .where(*conditions)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [ChatMessageOut.model_validate(row).model_dump() for row in rows]
    return ok(page_data(items, int(total), page, page_size))


@router.delete("/sessions/{session_id}", summary="删除会话")
def delete_session(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """删除本人某会话（消息级联删除，越权 → 404 / 4001）。"""
    session = _get_owned_session(db, session_id, current_user.id)
    # 显式按 id + user_id 删除，双保险（SQL 层数据隔离）
    db.execute(
        delete(ChatSession).where(
            ChatSession.id == session.id,
            ChatSession.user_id == current_user.id,
        )
    )
    db.commit()
    return ok(None)


# ============================================================
# 端点：SSE 流式问答
# ============================================================
@router.post("/sessions/{session_id}/messages", summary="发送消息（SSE 流式）")
async def send_message(
    session_id: int,
    payload: ChatMessageIn,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    """向已有会话发消息，SSE 流式返回（空/超长问题 → 400 / 4003；越权 → 404 / 4001）。"""
    # 校验必须在建立流之前完成：保证空/超长返回普通 JSON 400，而非流里的 error 帧
    question = _validate_question(payload.question)
    session = _get_owned_session(db, session_id, current_user.id)

    detection_ctx: DetectionContextOut | None = None
    class_filter: str | None = None
    crop: str | None = None
    if session.detection_id is not None:
        record = _get_owned_detection(db, session.detection_id, current_user.id)
        detection_ctx = _build_detection_context(record)
        class_filter = record.top_disease
        crop = _crop_of_class(record.top_disease)

    return _prepare_and_stream(
        request=request,
        db=db,
        session=session,
        question=question,
        detection_ctx=detection_ctx,
        class_filter=class_filter,
        crop=crop,
    )


@router.post("/ask", summary="直接提问（SSE，自动建会话）")
async def ask(
    payload: ChatAskIn,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    """直接提问：``session_id`` 为空则自动建会话；SSE 流式返回，meta 携带新会话 id。"""
    question = _validate_question(payload.question)

    # 1) 定位 / 创建会话
    if payload.session_id is not None:
        session = _get_owned_session(db, payload.session_id, current_user.id)
    else:
        detection_id = payload.detection_id
        if detection_id is not None:
            _get_owned_detection(db, detection_id, current_user.id)  # 越权 → 4001
        session = ChatSession(
            user_id=current_user.id,
            title=question[:100],
            detection_id=detection_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    # 2) 检测上下文：显式 detection_id 优先，否则用会话关联的检测记录
    det_id = payload.detection_id if payload.detection_id is not None else session.detection_id
    detection_ctx: DetectionContextOut | None = None
    record: DetectionRecord | None = None
    if det_id is not None:
        record = _get_owned_detection(db, det_id, current_user.id)
        detection_ctx = _build_detection_context(record)

    # 3) 类别软过滤 + 作物范围：显式 class_name 优先，否则用检测结论
    class_filter = payload.class_name or (record.top_disease if record is not None else None)
    crop = _crop_of_class(record.top_disease if record is not None else None)

    return _prepare_and_stream(
        request=request,
        db=db,
        session=session,
        question=question,
        detection_ctx=detection_ctx,
        class_filter=class_filter,
        crop=crop,
    )
