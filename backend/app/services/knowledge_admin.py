# -*- coding: utf-8 -*-
"""知识库运营服务：``kb/diseases/*.md``（事实源）× ``knowledge_docs``（镜像）× FAISS（产物）。

设计依据：``docs/impl-pc-admin-v1.md`` §6。

* 写文档：写 ``kb/diseases/<slug>.md`` → upsert ``knowledge_docs``（``vector_status='pending'``）；
* 重新向量化：**复用** ``scripts/build_index.py``（不重写一份）→ 回填 ``vector_status`` → ``rag_service.reload()``。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, settings
from app.core.database import SessionLocal
from app.models.knowledge import KnowledgeDoc


def _now_iso() -> str:
    """当前 UTC 时间 → ISO-8601 带 Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cfg(name: str, default: Any) -> Any:
    """读取配置键；键缺失时回退默认值（配置键由 T01 落 ``config.py``）。"""
    return getattr(settings, name, default)


class KnowledgeAdminService:
    """知识库文档写入与重新向量化编排。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._last_built_at: str | None = None
        self._count: int = 0
        self._error: str | None = None

    # ------------------------------------------------------------ 路径 / slug
    def docs_dir(self) -> Path:
        """``kb/diseases`` 目录（绝对路径）。"""
        return settings.kb_diseases_path

    def slugify(self, title: str) -> str:
        """标题 → 文件名主体 slug（中文安全）。

        规则：转小写 → 非字母/数字/中日韩字符替换为 ``-`` → 合并连续 ``-`` → 去首尾 ``-``。
        """
        text = (title or "").strip().lower()
        text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", text)
        text = re.sub(r"-+", "-", text).strip("-")
        return text or "doc"

    def parse_title(self, content_md: str, fallback: str) -> str:
        """取正文首个 H1（``# 标题``）作为标题；缺省用 ``fallback``。"""
        for line in (content_md or "").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                if title:
                    return title
        return fallback

    def _rel_source_path(self, slug: str) -> str:
        """返回 ``source_path``（优先相对仓库根的正斜杠路径，与既有行格式一致）。"""
        path = self.docs_dir() / f"{slug}.md"
        try:
            return path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    def source_path_for(self, slug: str) -> str:
        """公开：由 slug 计算 ``source_path``（不落盘，供冲突检测）。"""
        return self._rel_source_path(slug)

    # ------------------------------------------------------------ 文件读写
    def write_md(self, slug: str, content_md: str) -> str:
        """写 ``kb/diseases/<slug>.md``（UTF-8），返回 ``source_path``。"""
        directory = self.docs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{slug}.md"
        path.write_text(content_md, encoding="utf-8")
        return self._rel_source_path(slug)

    def delete_md(self, slug: str) -> None:
        """删除 ``kb/diseases/<slug>.md``（不存在则忽略，异常静默）。"""
        try:
            (self.docs_dir() / f"{slug}.md").unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"删除 md 文件失败（已忽略）：{slug}（{exc}）")

    # ------------------------------------------------------------ 文档镜像
    def get_by_id(self, db: Session, doc_id: int) -> KnowledgeDoc | None:
        """按主键取文档。"""
        return db.get(KnowledgeDoc, doc_id)

    def get_by_source_path(self, db: Session, source_path: str) -> KnowledgeDoc | None:
        """按 ``source_path`` 取文档（幂等 upsert 的键）。"""
        return db.scalar(select(KnowledgeDoc).where(KnowledgeDoc.source_path == source_path))

    def upsert_doc(
        self,
        db: Session,
        *,
        source_path: str,
        title: str,
        crop: str | None,
        disease: str | None,
        content_md: str,
        vector_status: str = "pending",
    ) -> KnowledgeDoc:
        """按 ``source_path`` upsert ``knowledge_docs``（新建立 ``vector_status='pending'``）。"""
        doc = self.get_by_source_path(db, source_path)
        if doc is None:
            doc = KnowledgeDoc(
                title=title,
                crop=crop,
                disease=disease,
                source_path=source_path,
                content_md=content_md,
                vector_status=vector_status,
            )
            db.add(doc)
        else:
            doc.title = title
            doc.crop = crop
            doc.disease = disease
            doc.content_md = content_md
            doc.vector_status = vector_status
        db.commit()
        db.refresh(doc)
        return doc

    def delete_doc(self, db: Session, doc: KnowledgeDoc) -> None:
        """删除文档行（md 文件由调用方按 slug 清理）。"""
        db.delete(doc)
        db.commit()

    # ------------------------------------------------------------ 重新向量化
    def reindex_async(self) -> bool:
        """后台触发重新向量化（幂等：已在运行则返回 ``False``）。"""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._error = None
        thread = threading.Thread(target=self._run_reindex, name="kb-reindex", daemon=True)
        thread.start()
        return True

    def reindex_status(self) -> dict:
        """当前重建状态 ``{running,last_built_at,count,error}``。"""
        with self._lock:
            return {
                "running": self._running,
                "last_built_at": self._last_built_at,
                "count": self._count,
                "error": self._error,
            }

    def _run_reindex(self) -> None:
        """子进程调用 ``scripts/build_index.py`` → 回填状态 → 热更 RAG。"""
        try:
            script = REPO_ROOT / "scripts" / "build_index.py"
            if not script.exists():
                raise FileNotFoundError(f"索引脚本不存在：{script}")
            timeout = int(_cfg("kb_reindex_timeout_seconds", 300) or 300)
            proc = subprocess.run(  # noqa: S603 —— 固定脚本路径，无用户输入拼接
                [sys.executable, str(script)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "")[-500:]
                raise RuntimeError(f"build_index.py 退出码 {proc.returncode}：{tail}")

            count = self._read_index_count()
            self._set_vector_status_all("done")
            self._reload_rag()
            with self._lock:
                self._count = count
                self._last_built_at = _now_iso()
            logger.info(f"知识库重新向量化完成：chunks={count}")
        except Exception as exc:  # noqa: BLE001 —— 重建失败仅记状态，不冒泡
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
            logger.warning(f"知识库重新向量化失败：{type(exc).__name__}: {exc}")
            self._set_vector_status_all("failed")
        finally:
            with self._lock:
                self._running = False

    def _read_index_count(self) -> int:
        """读取 ``kb/index/meta.json`` 的 ``count``；失败返回 0。"""
        meta_path = settings.faiss_index_path / "meta.json"
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return int(data.get("count", 0))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(f"读取索引 meta 失败：{exc}")
            return 0

    def _set_vector_status_all(self, status: str) -> None:
        """把所有 ``knowledge_docs.vector_status`` 批量置为给定状态（DB 不可用则静默）。"""
        db = SessionLocal()
        try:
            docs = db.scalars(select(KnowledgeDoc)).all()
            for doc in docs:
                doc.vector_status = status
            db.commit()
        except Exception as exc:  # noqa: BLE001 —— 状态回填失败不影响主流程
            logger.warning(f"回填 vector_status 失败（已忽略）：{type(exc).__name__}: {exc}")
        finally:
            db.close()

    def _reload_rag(self) -> None:
        """热更 RAG 索引（模块未就绪 / 加载失败一律静默降级）。"""
        try:
            from app.services.rag import rag_service  # noqa: PLC0415 —— 惰性导入，避免重量级依赖
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"RAG 服务不可用，跳过热更：{exc}")
            return
        try:
            rag_service.reload()
            logger.info("RAG 索引已热更")
        except Exception as exc:  # noqa: BLE001 —— 热更失败不影响重建结果
            logger.warning(f"RAG 热更失败（已忽略）：{type(exc).__name__}: {exc}")


# 模块级单例
knowledge_admin_service = KnowledgeAdminService()


__all__ = ["KnowledgeAdminService", "knowledge_admin_service"]
