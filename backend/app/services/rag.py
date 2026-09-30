# -*- coding: utf-8 -*-
"""RAG 检索服务：bge 向量化 + FAISS 精确检索 + 作物域约束 + 空索引降级。

设计依据：``docs/impl-rag-chat-v1.md`` §1.5 / §1.6 / §2.1；
P1 修复（team-lead 冻结契约）：新增 **作物域约束** ``search(query, top_k, crop)`` ，
命中库外作物时返回 ``scope_miss=True`` 且**不回退**捞别的作物，避免「张冠李戴」引用。

加载时机：**懒加载单例**（首次 ``search`` 触发）。任何缺失一律降级为「空结果」，绝不抛错。

关键环境变量（必须在导入 ``sentence_transformers``/``huggingface_hub`` **之前**设置）：
  * ``HF_ENDPOINT``  —— huggingface.co 不可达，必须走镜像（``huggingface_hub`` 在 import 时读取）；
  * ``HF_HUB_DISABLE_XET`` —— ``hf-xet`` 走 Xet CAS 协议而 hf-mirror 不代理该后端，开启会导致
    模型下载回落到极慢路径（实测 95.8MB：约 25min → 28s），故必须关闭。
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

# ---------------------------------------------------------------------------
# ⚠️ 环境变量必须在任何 huggingface_hub / sentence_transformers 导入之前设置
# ---------------------------------------------------------------------------
os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint or "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", settings.hf_hub_disable_xet or "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import faiss  # noqa: E402
import numpy as np  # noqa: E402
from loguru import logger  # noqa: E402

# 常见作物词表（**不在** PlantVillage-38 的 `crop_cn` 里）。
# 作用：纯文本提问出现这些作物名时，可判定「请求的作物知识库中没有任何文档」→
# ``scope_miss=True``（避免被误判为「未识别出作物」而回退全库、返回张冠李戴的引用）。
# 仅在 crop_cn / crop_en / aliases 全部未命中时作为兜底匹配使用，可按需裁剪。
EXTRA_CROP_LEXICON: tuple[str, ...] = (
    "水稻", "小麦", "大麦", "燕麦", "高粱", "谷子", "小米", "荞麦",
    "棉花", "油菜", "花生", "甘蔗", "甜菜", "向日葵", "芝麻",
    "茶树", "茶叶", "烟草", "咖啡", "可可",
    "黄瓜", "西瓜", "甜瓜", "冬瓜", "丝瓜", "苦瓜", "佛手瓜", "南瓜",
    "茄子", "辣椒", "彩椒",
    "白菜", "甘蓝", "花椰菜", "西兰花", "萝卜", "胡萝卜", "菠菜", "生菜", "芹菜",
    "韭菜", "大葱", "洋葱", "大蒜", "生姜", "山药", "芋头", "莲藕", "茭白", "芦笋", "竹笋",
    "香蕉", "芒果", "荔枝", "龙眼", "梨", "枣", "猕猴桃", "石榴", "火龙果",
    "番木瓜", "菠萝", "椰子", "杨梅", "枇杷", "柿子", "板栗", "核桃",
)

# ---------------------------------------------------------------------------
# P2 修复：用药/防治意图识别 + 章节排序加成
#   背景：知识库仅 30 chunk。「症状描述 + 用药意图」的混合提问（如「叶子有褐色斑该用什么药？
#   多久打一次？」）会把「四、防治方法」章节挤到第 5~10 名（分数仅略低），``rag_top_k=4``
#   时漏召回 → 模型误答「知识库暂无相关权威资料」。除提高 ``rag_top_k`` 外，本加成在
#   **不改变 min_score 阈值、不改变作物域约束、不改变 score 语义**（score 仍为原始余弦相似度）的
#   前提下，仅对命中「用药/防治」意图的 query 把「防治/用药」章节 chunk 小幅提前排序，
#   提高其进入上下文的概率。纯重排，不增删任何 chunk。
# ---------------------------------------------------------------------------
_MED_INTENT_KEYWORDS: tuple[str, ...] = (
    "用药", "打药", "喷药", "施药", "配药", "药剂", "药", "防治", "怎么治", "如何治",
    "杀菌剂", "杀虫剂", "杀螨剂", "多少倍", "稀释", "浓度", "间隔", "多久", "几天", "几次",
)
_MED_SECTION_KEYWORDS: tuple[str, ...] = ("防治", "用药")
_MED_INTENT_BONUS: float = 0.04


def _has_medication_intent(query: str) -> bool:
    """判断 query 是否表达「用药/防治」意图（关键词命中即视为命中，用于章节排序加成）。"""
    text = query or ""
    return any(kw in text for kw in _MED_INTENT_KEYWORDS)


@dataclass
class RetrievedChunk:
    """单条检索命中。"""

    i: int                       # FAISS 下标（与向量顺序一致）
    doc_slug: str
    doc_db_id: int | None
    title: str                   # 文档标题（disease_cn）
    class_name: str | None       # 模型原始类名（用于过滤/聚合）
    crop_cn: str | None
    category: str | None         # 真菌/细菌/卵菌/病毒/虫害/检疫性/健康
    section: str                 # 章节标题（如「二、症状识别」）
    text: str                    # 上下文头 + 正文
    score: float                 # 排序分：原始余弦相似度；用药/防治意图下对「防治/用药」章节 +0.04
    source_path: str | None

    def to_citation(self) -> dict:
        """→ ``chat_messages.citations`` 元素 ``{doc_id,title,snippet}``。"""
        snippet = self.text[:120].replace("\n", " ")
        return {
            "doc_id": self.doc_slug,
            "title": f"{self.title}·{self.section}",
            "snippet": snippet,
        }


@dataclass(eq=False)
class SearchResult:
    """一次检索的结果信封（P1 冻结契约，工程师 B 按此消费）。"""

    chunks: list[RetrievedChunk] = field(default_factory=list)
    scope_miss: bool = False       # True = 请求的作物在知识库中没有任何文档
    crop_scope: str | None = None  # 实际生效的作物约束（诊断用）

    def __bool__(self) -> bool:
        """便于 ``if result:`` 判空。"""
        return bool(self.chunks)

    def __eq__(self, other: object) -> bool:
        """**向后兼容**：允许与旧契约的 ``list`` / ``tuple`` 直接比较（等价于比较 ``chunks``）。

        例：``search(q) == []`` 在无命中时为 ``True``。
        """
        if isinstance(other, SearchResult):
            return (
                self.chunks == other.chunks
                and self.scope_miss == other.scope_miss
                and self.crop_scope == other.crop_scope
            )
        if isinstance(other, list):
            return list(self.chunks) == other
        if isinstance(other, tuple):
            return tuple(self.chunks) == other
        return NotImplemented


class RagService:
    """向量检索服务（线程安全懒加载单例）。

    设计要点：
      * 进程启动**不加载**模型与索引；首次检索时懒加载（``threading.Lock`` 保护）；
      * 索引 / 模型缺失或校验失败 → ``_ready=False``，``search`` 返回空信封（不抛错）；
      * **作物域约束**：``crop`` 非空 → 只在该作物范围内检索；库中无该作物 → ``scope_miss=True``；
        ``crop`` 为空 → 先做查询文本作物识别，识别不出才回退全库检索。
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._index: Any = None
        self._chunks: list[dict] = []
        self._meta: dict = {}
        self._lock = threading.RLock()
        self._ready: bool = False
        # 作物索引缓存（懒构建，reload 时清空）
        self._crops: dict | None = None
        self._avail_crops: set[str] | None = None

    # ------------------------------------------------------------------ 路径
    @property
    def _index_dir(self):
        """索引目录（含 ``faiss.index`` / ``chunks.json`` / ``meta.json``）。"""
        return settings.faiss_index_path

    # --------------------------------------------------------------- 懒加载
    def ensure_loaded(self) -> bool:
        """懒加载 embedding 模型 + FAISS 索引 + chunks。

        Returns:
            ``True`` = 就绪；``False`` = 降级（索引/模型缺失或校验失败）。
        线程锁保护，只执行一次；失败后保持降级状态（可用 :meth:`reload` 重试）。
        """
        if self._ready:
            return True
        with self._lock:
            if self._ready:
                return True
            try:
                if not self._load_index_and_chunks():
                    return False
                if not self._load_model():
                    self._reset()
                    return False
                self._ready = True
                logger.info(
                    f"RAG 就绪：model={settings.embedding_model} dim={self._meta.get('dim')} "
                    f"count={len(self._chunks)} crops={sorted(self._available_crops())}"
                )
                return True
            except Exception as exc:  # noqa: BLE001 —— 任何异常一律降级，绝不向上抛
                logger.error(f"RAG 加载失败，降级为空索引：{type(exc).__name__}: {exc}")
                self._reset()
                return False

    def _load_index_and_chunks(self) -> bool:
        """加载并校验索引三件套。校验失败返回 ``False``（视为空索引）。"""
        index_dir = self._index_dir
        faiss_file = index_dir / "faiss.index"
        chunks_file = index_dir / "chunks.json"
        meta_file = index_dir / "meta.json"

        missing = [p.name for p in (faiss_file, chunks_file, meta_file) if not p.exists()]
        if missing:
            logger.warning(f"FAISS 索引不完整（缺少 {missing}），降级为空索引")
            return False

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        chunks = json.loads(chunks_file.read_text(encoding="utf-8"))
        index = faiss.read_index(str(faiss_file))

        # ---- 一致性校验（任一不满足 → 视为空索引）----
        if meta.get("embedding_model") != settings.embedding_model:
            logger.error(
                f"索引 embedding_model 不匹配（meta={meta.get('embedding_model')} "
                f"!= settings={settings.embedding_model}），视为空索引"
            )
            return False
        if int(meta.get("dim", -1)) != int(index.d):
            logger.error(f"索引维度不一致（meta.dim={meta.get('dim')} != index.d={index.d}）")
            return False
        if not (int(meta.get("count", -1)) == int(index.ntotal) == len(chunks)):
            logger.error(
                f"索引数量不一致（meta.count={meta.get('count')} index.ntotal={index.ntotal} "
                f"chunks={len(chunks)}）"
            )
            return False
        if len(chunks) == 0:
            logger.warning("chunks 为空，降级为空索引")
            return False

        self._meta = meta
        self._chunks = chunks
        self._index = index
        return True

    def _load_model(self) -> bool:
        """加载 bge 模型（延迟导入 ``sentence_transformers``，避免拖慢应用启动）。"""
        try:
            from sentence_transformers import SentenceTransformer  # 延迟导入
        except Exception as exc:  # noqa: BLE001
            logger.error(f"导入 sentence_transformers 失败：{type(exc).__name__}: {exc}")
            return False
        try:
            self._model = SentenceTransformer(settings.embedding_model, device="cpu")
            return True
        except Exception as exc:  # noqa: BLE001 —— 模型未下载 / 网络不可达
            logger.error(f"加载 bge 模型失败（可能未下载）：{type(exc).__name__}: {exc}")
            return False

    def _reset(self) -> None:
        """清空已加载资源并置降级。"""
        self._model = None
        self._index = None
        self._chunks = []
        self._meta = {}
        self._ready = False
        self._crops = None
        self._avail_crops = None

    # --------------------------------------------------------------- 状态
    def is_ready(self) -> bool:
        """健康检查用；**不触发加载**。"""
        return self._ready

    # ------------------------------------------------------- 作物索引与识别
    def _crop_maps(self) -> dict:
        """（懒构建）从 ``kb/class-map.json`` 构建作物识别所需的映射。"""
        if self._crops is not None:
            return self._crops
        path = settings.kb_class_map_abs
        rows: list[dict] = []
        if path.exists():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                rows = []
        cls2cn: dict[str, str] = {}
        slug2cn: dict[str, str] = {}
        en2cn: dict[str, str] = {}
        alias2cns: dict[str, set[str]] = {}
        crop_cns: set[str] = set()
        for row in rows:
            cn = (row.get("crop_cn") or "").strip()
            if not cn:
                continue
            crop_cns.add(cn)
            if row.get("class_name"):
                cls2cn[row["class_name"]] = cn
            if row.get("slug"):
                slug2cn[row["slug"]] = cn
            en = (row.get("crop_en") or "").strip()
            if en:
                en2cn[en.lower()] = cn
            for alias in (row.get("aliases") or []):
                alias = (alias or "").strip()
                if alias:
                    alias2cns.setdefault(alias, set()).add(cn)
        self._crops = {
            "cls2cn": cls2cn,
            "slug2cn": slug2cn,
            "en2cn": en2cn,
            "alias2cns": alias2cns,
            "crop_cns": sorted(crop_cns, key=len, reverse=True),  # 长词优先，避免「桃」抢「樱桃」
            "crop_cn_set": crop_cns,
        }
        return self._crops

    def _available_crops(self) -> set[str]:
        """（懒构建）知识库中**已有文档**的作物集合（依据 ``kb/diseases/*.md``）。"""
        if self._avail_crops is not None:
            return self._avail_crops
        maps = self._crop_maps()
        slugs = {p.stem for p in settings.kb_diseases_path.glob("*.md")} \
            if settings.kb_diseases_path.exists() else set()
        self._avail_crops = {maps["slug2cn"][s] for s in slugs if s in maps["slug2cn"]}
        return self._avail_crops

    def _normalize_crop(self, crop: str | None) -> str | None:
        """把检测上下文的作物标识（类名 / 英文名 / 中文名）归一为 ``crop_cn``。"""
        text = (crop or "").strip()
        if not text:
            return None
        maps = self._crop_maps()
        if text in maps["cls2cn"]:
            return maps["cls2cn"][text]
        if "___" in text:  # 类名形态但未精确命中 → 取前缀英文名
            prefix = text.split("___", 1)[0]
            if prefix.lower() in maps["en2cn"]:
                return maps["en2cn"][prefix.lower()]
        if text in maps["crop_cn_set"]:
            return text
        if text.lower() in maps["en2cn"]:
            return maps["en2cn"][text.lower()]
        for cn in maps["crop_cns"]:  # 退一步：包含关系
            if cn in text:
                return cn
        return text  # 原样返回（当作作物名使用）

    def _detect_crop(self, query: str) -> str | None:
        """纯文本提问的作物识别：crop_cn → crop_en → aliases → 兜底词表。

        仅在**唯一**命中时返回作物名；多作物歧义时返回 ``None``（交由全库检索回落）。
        """
        maps = self._crop_maps()
        # 1) 中文作物名（长词优先；去掉被更长命中词包含的短词，避免「桃」误抢「樱桃」）
        present = [cn for cn in maps["crop_cns"] if cn in query]
        if present:
            present = [t for t in present if not any(t != o and t in o for o in present)]
            if len(present) == 1:
                return present[0]
            return None
        # 2) 英文作物名
        low = query.lower()
        en_hits = {cn for en, cn in maps["en2cn"].items() if en and en in low}
        if len(en_hits) == 1:
            return next(iter(en_hits))
        if len(en_hits) > 1:
            return None
        # 3) 病害别名 → 作物
        alias_hits: set[str] = set()
        for alias, cns in maps["alias2cns"].items():
            if alias in query:
                alias_hits |= cns
        if len(alias_hits) == 1:
            return next(iter(alias_hits))
        if len(alias_hits) > 1:
            return None
        # 4) 库外常见作物兜底词表
        for name in EXTRA_CROP_LEXICON:
            if name in query:
                return name
        return None

    # --------------------------------------------------------------- 编码
    def embed_query(self, query: str) -> "np.ndarray | None":
        """query → 归一化向量 ``(1, dim)``；未就绪返回 ``None``。

        BGE 中文 s2p 推荐：query 侧加指令前缀，passage 侧不加（由 ``RAG_QUERY_INSTRUCTION`` 控制）。
        """
        if not self._ready or self._model is None:
            return None
        try:
            instruction = settings.rag_query_instruction or ""
            text = f"{instruction}{query}" if instruction else query
            vec = self._model.encode(
                [text],
                normalize_embeddings=True,
                batch_size=settings.embedding_batch_size,
                show_progress_bar=False,
            )
            return np.asarray(vec, dtype="float32")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"query 向量化失败：{type(exc).__name__}: {exc}")
            return None

    # --------------------------------------------------------------- 检索
    def search(
        self,
        query: str,
        top_k: int | None = None,
        crop: str | None = None,
    ) -> SearchResult:
        """检索 Top-K（**P1 冻结契约**）。

        Args:
            query: 用户问题。
            top_k: 返回条数，缺省取 ``settings.rag_top_k``。
            crop: 作物约束。可为 ``crop_cn``（如「番茄」）、``crop_en``（如 ``Tomato``）
                或检测类名（如 ``Tomato___Late_blight``）。

        Returns:
            :class:`SearchResult`：
              * ``crop`` 非空且库中有该作物 → 只在该作物范围内检索；
              * ``crop`` 非空但库中无该作物 → ``chunks=[]``、``scope_miss=True``（**不回退**）；
              * ``crop`` 为空 → 查询文本识别作物：
                  - 识别出且库中有 → 限定该作物检索；
                  - 识别出但库中无 → ``scope_miss=True``；
                  - 完全未识别出 → 全库检索 + ``rag_min_score`` 阈值；
              * 空索引 / 模型未就绪 / 空 query → ``SearchResult(chunks=[])``，**不抛错**。
        """
        if not query or not query.strip():
            logger.warning("RAG 检索：query 为空，返回空结果")
            return SearchResult()
        if not self.ensure_loaded():
            logger.warning("RAG 检索：索引/模型未就绪，返回空结果（降级）")
            return SearchResult()
        try:
            return self._do_search(query, top_k, crop)
        except Exception as exc:  # noqa: BLE001 —— 检索异常同样降级为空结果
            logger.error(f"RAG 检索异常，返回空结果：{type(exc).__name__}: {exc}")
            return SearchResult()

    def _do_search(self, query: str, top_k: int | None, crop: str | None) -> SearchResult:
        """按契约执行「作物域约束 → 向量检索」。"""
        k = int(top_k) if top_k is not None else int(settings.rag_top_k)
        if k <= 0:
            return SearchResult()

        # 分支 1：显式给定作物（来自检测上下文）
        if crop and crop.strip():
            scope = self._normalize_crop(crop)
            if scope and scope not in self._available_crops():
                logger.info(f"RAG 作物域未命中：请求作物『{scope}』库中无文档 → scope_miss")
                return SearchResult(chunks=[], scope_miss=True, crop_scope=scope)
            chunks = self._vector_search(query, k, crop_filter=scope)
            return SearchResult(chunks=chunks, scope_miss=False, crop_scope=scope)

        # 分支 2：纯文本提问 → 先做作物识别
        detected = self._detect_crop(query)
        if detected:
            if detected not in self._available_crops():
                logger.info(f"RAG 识别到作物『{detected}』但库中无文档 → scope_miss")
                return SearchResult(chunks=[], scope_miss=True, crop_scope=detected)
            chunks = self._vector_search(query, k, crop_filter=detected)
            return SearchResult(chunks=chunks, scope_miss=False, crop_scope=detected)

        # 分支 2c：未识别出作物 → 全库检索 + 阈值
        chunks = self._vector_search(query, k, crop_filter=None)
        return SearchResult(chunks=chunks, scope_miss=False, crop_scope=None)

    def _vector_search(self, query: str, k: int, crop_filter: str | None) -> list[RetrievedChunk]:
        """向量检索核心：可选按 ``crop_cn`` 严格过滤（**不做跨作物补足**）。"""
        vec = self.embed_query(query)
        if vec is None:
            return []
        threshold = float(settings.rag_min_score)
        ntotal = int(self._index.ntotal)
        if ntotal <= 0:
            return []
        if crop_filter:
            # 需在候选里筛出目标作物；小库全量、大库放大候选数
            fetch = ntotal if ntotal <= 2000 else min(ntotal, max(k * 50, 500))
        else:
            fetch = min(ntotal, k)
        scores, indices = self._index.search(vec, fetch)

        # P2 修复：用药/防治意图 → 对「防治/用药」章节 chunk 做小幅**排序加成**。
        # 注意：阈值过滤（score < threshold）仍用**原始余弦**；score 语义不变；仅影响顺序。
        boost = _MED_INTENT_BONUS if _has_medication_intent(query) else 0.0
        ranked: list[tuple[float, RetrievedChunk]] = []
        for score, idx in zip(scores[0].tolist(), indices[0].tolist()):
            if idx < 0 or idx >= len(self._chunks):
                continue
            if score < threshold:
                continue
            if crop_filter and self._chunks[idx].get("crop_cn") != crop_filter:
                continue  # 严格作物域：不回退、不补足
            order_score = float(score)
            section = self._chunks[idx].get("section", "") or ""
            if boost and any(kw in section for kw in _MED_SECTION_KEYWORDS):
                order_score += boost  # 纯排序加成：仅提升「防治/用药」章节位次
            ranked.append((order_score, self._to_chunk(idx, order_score)))
        # 稳定排序：加成后降序；同分保持 FAISS 原（相似度）顺序
        ranked.sort(key=lambda item: -item[0])
        return [chunk for _, chunk in ranked[:k]]

    def _to_chunk(self, idx: int, score: float) -> RetrievedChunk:
        """把 FAISS 下标 + 分数组装为 :class:`RetrievedChunk`。"""
        raw = self._chunks[idx]
        return RetrievedChunk(
            i=idx,
            doc_slug=raw.get("doc_slug", ""),
            doc_db_id=raw.get("doc_db_id"),
            title=raw.get("title", ""),
            class_name=raw.get("class_name"),
            crop_cn=raw.get("crop_cn"),
            category=raw.get("category"),
            section=raw.get("section", ""),
            text=raw.get("text", ""),
            score=score,
            source_path=raw.get("source_path"),
        )

    # --------------------------------------------------------------- 重载
    def reload(self) -> bool:
        """显式重载（重建索引后热更用）。"""
        with self._lock:
            self._reset()
        return self.ensure_loaded()


# 模块级单例
rag_service = RagService()


def is_ready() -> bool:
    """健康检查入口：RAG 是否已就绪（不触发加载）。"""
    return rag_service.is_ready()


__all__ = ["RetrievedChunk", "SearchResult", "RagService", "rag_service", "is_ready"]
