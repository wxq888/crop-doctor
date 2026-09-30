# -*- coding: utf-8 -*-
"""构建 RAG 向量索引：``kb/diseases/`` 一病一档 → 切分 → bge 向量化 → FAISS 持久化。

设计依据：``docs/impl-rag-chat-v1.md`` §1.5 / §1.6 / T02。
  * 切分：按 ``## ``（H2）标题切分 + 上下文头；单节超长按句再切（overlap）；过短与相邻节合并；
  * 向量：``BAAI/bge-small-zh-v1.5``（512 维），``normalize_embeddings=True``，passage 侧不加指令；
  * 索引：``faiss.IndexFlatIP``（精确内积 ≡ 余弦）；
  * 持久化：``kb/index/{faiss.index,chunks.json,meta.json}`` 三者同版本，写临时目录后**原子替换**；
  * 幂等：重复运行命中本地模型缓存，不重复下载；按 ``source_path`` 回填 ``doc_db_id``/``vector_status``。

用法（在仓库根执行）::

    .venv\\Scripts\\python.exe scripts\\build_index.py
    .venv\\Scripts\\python.exe scripts\\build_index.py --no-db
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timezone

# —— 必须在导入 sentence_transformers / huggingface_hub 之前设置环境变量 ——
from kb_common import doc_rows, has_grade_a_source, load_class_map, review_state  # noqa: E402

from app.core.config import settings  # noqa: E402

os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint or "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", settings.hf_hub_disable_xet or "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import faiss  # noqa: E402
import numpy as np  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

# 中文句末切分点
_SENT_RE = re.compile(r"(?<=[。！？；!?;])")
# 单节过短阈值（设计 §1.5.1）
_MIN_SECTION_CHARS = 40


# ---------------------------------------------------------------------------
# Markdown 解析与切分
# ---------------------------------------------------------------------------
def parse_markdown(md_text: str) -> tuple[str, list[tuple[str, str]]]:
    """解析一病一档：返回 ``(H1 标题, [(H2 章节标题, 正文), ...])``。

    H1 与文档级引用块（``>``）仅作元数据，不作为 chunk。
    """
    title = ""
    sections: list[tuple[str, str]] = []
    cur_title: str | None = None
    buf: list[str] = []
    for line in md_text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, "\n".join(buf).strip()))
            cur_title = line[3:].strip()
            buf = []
        elif cur_title is not None:
            buf.append(line)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(buf).strip()))
    return title, sections


def merge_short_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """把过短（< 40 字）的节与相邻同级节合并，避免噪声 chunk。"""
    merged: list[tuple[str, str]] = []
    for title, body in sections:
        if not body:
            continue
        if merged and len(merged[-1][1]) < _MIN_SECTION_CHARS:
            prev_title, prev_body = merged[-1]
            merged[-1] = (f"{prev_title}／{title}", f"{prev_body}\n{body}".strip())
        else:
            merged.append((title, body))
    # 末尾仍过短则并入前一个
    if len(merged) >= 2 and len(merged[-1][1]) < _MIN_SECTION_CHARS:
        tail_title, tail_body = merged.pop()
        prev_title, prev_body = merged[-1]
        merged[-1] = (f"{prev_title}／{tail_title}", f"{prev_body}\n{tail_body}".strip())
    return merged


def split_long_body(body: str, max_chars: int, overlap: int) -> list[str]:
    """单节超长时按句再切，相邻片重叠 ``overlap`` 字。"""
    if len(body) <= max_chars:
        return [body]
    sentences = [s for s in _SENT_RE.split(body) if s.strip()]
    pieces: list[str] = []
    cur = ""
    for sent in sentences:
        # 单句本身就超长 → 直接硬切
        if len(sent) > max_chars:
            if cur:
                pieces.append(cur)
                cur = ""
            start = 0
            while start < len(sent):
                pieces.append(sent[start:start + max_chars])
                start += max_chars - overlap
            continue
        if len(cur) + len(sent) <= max_chars:
            cur += sent
        else:
            pieces.append(cur)
            tail = cur[-overlap:] if overlap > 0 else ""
            cur = tail + sent
    if cur.strip():
        pieces.append(cur)
    return [p for p in pieces if p.strip()]


def build_chunks_for_doc(row: dict, md_text: str) -> list[dict]:
    """把单篇文档切分为 chunk 列表（含上下文头）。"""
    _, sections = parse_markdown(md_text)
    sections = merge_short_sections(sections)
    crop_cn = row.get("crop_cn") or ""
    disease_cn = row.get("disease_cn") or ""
    max_chars = int(settings.rag_chunk_max_chars)
    overlap = int(settings.rag_chunk_overlap_chars)
    src = f"kb/diseases/{row['slug']}.md"
    # 审校三态（由 reviewed_by 派生），写入 chunk 元数据供前端徽标 / 答辩审计（纯新增字段）
    review_status = review_state(row)

    chunks: list[dict] = []
    for section_title, body in sections:
        header = f"【{crop_cn}】【{disease_cn}】\n## {section_title}\n"
        for piece in split_long_body(body, max_chars, overlap):
            chunks.append({
                "doc_slug": row["slug"],
                "class_name": row["class_name"],
                "title": disease_cn,
                "crop_cn": crop_cn,
                "category": row.get("category"),
                "section": section_title,
                "text": header + piece,
                "source_path": src,
                "review_status": review_status,
            })
    return chunks


# ---------------------------------------------------------------------------
# 数据库辅助（best-effort）
# ---------------------------------------------------------------------------
def resolve_db_ids(slugs: list[str]) -> dict[str, int]:
    """按 ``source_path`` 查询 ``knowledge_docs.id``（库不可用时返回空映射）。"""
    try:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models.knowledge import KnowledgeDoc

        db = SessionLocal()
        try:
            rows = db.scalars(
                select(KnowledgeDoc).where(
                    KnowledgeDoc.source_path.in_([f"kb/diseases/{s}.md" for s in slugs])
                )
            ).all()
            return {r.source_path.rsplit("/", 1)[-1][:-3]: r.id for r in rows}
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 —— 库不可用不阻塞索引构建
        print(f"  ⚠ 读取 knowledge_docs 失败（跳过 doc_db_id 回填）：{type(exc).__name__}: {exc}")
        return {}


def mark_done(slugs: list[str]) -> None:
    """构建成功后把对应文档 ``vector_status`` 置 ``done``（best-effort）。"""
    try:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models.knowledge import KnowledgeDoc

        db = SessionLocal()
        try:
            rows = db.scalars(
                select(KnowledgeDoc).where(
                    KnowledgeDoc.source_path.in_([f"kb/diseases/{s}.md" for s in slugs])
                )
            ).all()
            for rec in rows:
                rec.vector_status = "done"
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ 回填 vector_status 失败：{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def collect_documents() -> tuple[list[dict], list[str]]:
    """收集可建索引的文档：``kb/diseases/<slug>.md`` 存在 且通过诚信校验。"""
    rows = load_class_map()
    diseases_dir = settings.kb_diseases_path
    docs: list[dict] = []
    skipped: list[str] = []
    for row in doc_rows(rows):
        md_path = diseases_dir / f"{row['slug']}.md"
        if not md_path.exists():
            continue  # 未定稿文档直接忽略（不是错误）
        if not row.get("reviewed_by"):
            skipped.append(f"{row['slug']}（reviewed_by 为空）")
            continue
        if not has_grade_a_source(row):
            skipped.append(f"{row['slug']}（无 A 级来源）")
            continue
        docs.append({"row": row, "md": md_path.read_text(encoding="utf-8")})
    return docs, skipped


def build(args: argparse.Namespace) -> int:
    """构建并持久化索引，返回退出码。"""
    docs, skipped = collect_documents()
    if skipped:
        print(f"跳过 {len(skipped)} 篇未通过诚信校验的文档：{', '.join(skipped)}")
    if not docs:
        print("无可建索引的文档（kb/diseases/ 为空或均未审校）。未生成索引，search() 将降级返回 []。")
        return 1

    chunks: list[dict] = []
    for doc in docs:
        chunks.extend(build_chunks_for_doc(doc["row"], doc["md"]))

    db_ids = resolve_db_ids([d["row"]["slug"] for d in docs]) if not args.no_db else {}
    for i, chunk in enumerate(chunks):
        chunk["i"] = i
        chunk["doc_db_id"] = db_ids.get(chunk["doc_slug"])

    print(f"加载 embedding 模型：{settings.embedding_model}（HF_ENDPOINT={os.environ.get('HF_ENDPOINT')}，"
          f"HF_HUB_DISABLE_XET={os.environ.get('HF_HUB_DISABLE_XET')}）")
    model = SentenceTransformer(settings.embedding_model, device="cpu")
    texts = [c["text"] for c in chunks]
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=int(settings.embedding_batch_size),
        show_progress_bar=False,
    )
    vectors = np.asarray(vectors, dtype="float32")
    dim = int(vectors.shape[1])

    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    meta = {
        "embedding_model": settings.embedding_model,
        "dim": dim,
        "count": len(chunks),
        "query_instruction": settings.rag_query_instruction,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kb_version": 1,
    }

    # —— 写临时目录 → 校验 → 原子替换 ——
    index_dir = settings.faiss_index_path
    tmp_dir = index_dir / ".tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(tmp_dir / "faiss.index"))
    (tmp_dir / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tmp_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 校验临时产物可回读
    check_index = faiss.read_index(str(tmp_dir / "faiss.index"))
    check_chunks = json.loads((tmp_dir / "chunks.json").read_text(encoding="utf-8"))
    if check_index.d != dim or check_index.ntotal != len(check_chunks):
        raise RuntimeError(
            f"临时索引校验失败：dim={check_index.d} ntotal={check_index.ntotal} chunks={len(check_chunks)}"
        )

    index_dir.mkdir(parents=True, exist_ok=True)
    for name in ("faiss.index", "chunks.json", "meta.json"):
        os.replace(tmp_dir / name, index_dir / name)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    if not args.no_db:
        mark_done([d["row"]["slug"] for d in docs])

    print("=== 索引构建完成 ===")
    print(f"文档数：{len(docs)}　chunk 数：{len(chunks)}　维度：{dim}")
    dist = Counter(c.get("review_status", "unverified") for c in chunks)
    print(f"review_status 分布：{dict(sorted(dist.items()))}")
    print(f"产物：{index_dir.as_posix()}/{{faiss.index,chunks.json,meta.json}}")
    for doc in docs:
        n = sum(1 for c in chunks if c["doc_slug"] == doc["row"]["slug"])
        print(f"  · {doc['row']['slug']:<46} {n} chunks")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="构建 RAG FAISS 索引")
    parser.add_argument("--no-db", action="store_true", help="不读写数据库（离线构建）")
    return parser


def main() -> int:
    """命令行入口。"""
    args = build_parser().parse_args()
    try:
        return build(args)
    except Exception as exc:  # noqa: BLE001 —— 顶层兜底
        print(f"索引构建异常：{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
