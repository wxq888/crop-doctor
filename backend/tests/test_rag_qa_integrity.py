# -*- coding: utf-8 -*-
"""QA 独立验证：RAG 索引三件套一致性与 chunk↔向量对应关系。

覆盖本轮最易出错、且此前无人验证的点：
- ``kb/index/{faiss.index,chunks.json,meta.json}`` 三者版本一致（count/dim/model）；
- ``chunks[i]`` 与 FAISS 第 i 个向量**真的是同一段文本**（passage 侧重新编码应自命中 top1）；
- 空索引 / 索引目录缺失 → ``search()`` 返回 ``[]`` 且不抛错（降级红线）;
- ``to_citation()`` 结构符合 ``chat_messages.citations`` 约定。

产物缺失（``kb/index`` 未构建，CI 常见）时一律 ``skip``，不产生假失败。
"""
import json

import pytest

from app.core.config import settings

# 先导入 rag 模块：其在导入期 setdefault HF_ENDPOINT / HF_HUB_DISABLE_XET，
# 保证随后 import sentence_transformers 时镜像与 Xet 开关已就位。
import app.services.rag  # noqa: E402,F401

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")

INDEX_DIR = settings.faiss_index_path


def _index_available() -> bool:
    return all((INDEX_DIR / n).exists() for n in ("faiss.index", "chunks.json", "meta.json"))


@pytest.mark.skipif(not _index_available(), reason="kb/index 未构建（缺少索引三件套）")
def test_index_triplet_consistency() -> None:
    """meta.dim == index.d，meta.count == index.ntotal == len(chunks)，模型名一致。"""
    import faiss

    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
    index = faiss.read_index(str(INDEX_DIR / "faiss.index"))

    assert meta["embedding_model"] == settings.embedding_model
    assert meta["dim"] == index.d == 512
    assert meta["count"] == index.ntotal == len(chunks)
    assert len(chunks) > 0
    # 下标连续且等于数组下标（FAISS 顺序对齐）
    assert all(c["i"] == i for i, c in enumerate(chunks))
    # 每条 chunk 必备字段齐全
    required = {"doc_slug", "title", "class_name", "crop_cn", "category", "section", "text", "source_path"}
    for c in chunks:
        assert required <= set(c), f"{c.get('i')} 缺字段：{required - set(c)}"


@pytest.mark.skipif(not _index_available(), reason="kb/index 未构建（缺少索引三件套）")
def test_chunk_vector_correspondence() -> None:
    """抽验 chunk[i] 与 FAISS 第 i 个向量一致：重新编码该 chunk 文本应自命中 top1。"""
    import faiss
    import numpy as np

    from sentence_transformers import SentenceTransformer

    chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
    index = faiss.read_index(str(INDEX_DIR / "faiss.index"))
    try:
        model = SentenceTransformer(settings.embedding_model, device="cpu")
    except Exception as exc:  # noqa: BLE001 —— 模型不可用时跳过（离线/无缓存）
        pytest.skip(f"bge 模型不可用：{exc}")

    probes = [0, len(chunks) // 2, len(chunks) - 1]
    for pid in probes:
        vec = np.asarray(
            model.encode([chunks[pid]["text"]], normalize_embeddings=True, show_progress_bar=False),
            dtype="float32",
        )
        _, idxs = index.search(vec, 1)
        assert int(idxs[0][0]) == pid, f"chunk[{pid}] 自命中失败，top1={int(idxs[0][0])}"


def test_missing_index_dir_degrades_to_empty(monkeypatch, tmp_path) -> None:
    """索引目录不存在 → search() 返回 [] 且不抛错（空索引降级红线）。"""
    monkeypatch.setattr(settings, "faiss_index_dir", str(tmp_path / "nonexistent"))
    from app.services.rag import RagService

    svc = RagService()
    assert svc.ensure_loaded() is False
    assert svc.is_ready() is False
    assert svc.search("番茄晚疫病怎么防治") == []


def test_empty_query_returns_empty(monkeypatch) -> None:
    """空 query / 纯空白 query → []，且不触发加载。"""
    from app.services.rag import RagService

    svc = RagService()
    assert svc.search("") == []
    assert svc.search("   ") == []
    assert svc.embed_query("任意") is None  # 未就绪


@pytest.mark.skipif(not _index_available(), reason="kb/index 未构建（缺少索引三件套）")
def test_citation_shape_matches_contract() -> None:
    """``RetrievedChunk.to_citation()`` → ``{doc_id,title,snippet}``（title 形如「病名·章节」）。"""
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["count"] > 0
    chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
    from app.services.rag import RetrievedChunk

    raw = chunks[0]
    chunk = RetrievedChunk(
        i=raw["i"], doc_slug=raw["doc_slug"], doc_db_id=raw.get("doc_db_id"), title=raw["title"],
        class_name=raw.get("class_name"), crop_cn=raw.get("crop_cn"), category=raw.get("category"),
        section=raw["section"], text=raw["text"], score=0.9, source_path=raw.get("source_path"),
    )
    cit = chunk.to_citation()
    assert set(cit.keys()) == {"doc_id", "title", "snippet"}
    assert cit["doc_id"] == raw["doc_slug"]
    assert "·" in cit["title"]
    assert len(cit["snippet"]) <= 120
    assert "\n" not in cit["snippet"]
