# -*- coding: utf-8 -*-
"""知识库入库脚本：校验「人工审校卡点」→ upsert 到 ``knowledge_docs``。

诚信红线（设计文档 §1.4.5）三态闸门 ——
  * ``reviewed_by`` 为空 → **拒绝入库**并报错退出；
  * ``reviewed_by`` 以 ``PENDING:`` 开头 → **允许入库**（供演示），
    但打印醒目告警，并在汇总**单列「未审校 N 篇」**（机器可识别、可审计）；
  * 其他（真实审校人）→ 正常入库。
无论哪种状态，``sources`` 都必须含 ≥1 个 A 级来源（``--force`` 仅供本地调试，生产禁用）。

幂等：以 ``knowledge_docs.source_path`` 为键 upsert，重复运行不产生重复行；
``vector_status`` 新建时置 ``pending``（由 ``scripts/build_index.py`` 构建索引后置 ``done``）。

用法（在仓库根执行）::

    .venv\\Scripts\\python.exe scripts\\ingest_kb.py                 # 入库 kb/diseases/ 下已审校文档
    .venv\\Scripts\\python.exe scripts\\ingest_kb.py --dry-run       # 只校验，不写库
    .venv\\Scripts\\python.exe scripts\\ingest_kb.py --slug apple-apple-scab   # 定向校验（演示拒绝）
"""
from __future__ import annotations

import argparse

# 先导入 kb_common（其内部已把 backend 加入 sys.path），再导入 app.*
from kb_common import (  # noqa: E402
    doc_rows,
    has_grade_a_source,
    load_class_map,
    review_state,
)

from app.core.config import settings  # noqa: E402


def _validate(row: dict, md_path, md_text: str | None, force: bool) -> str | None:
    """校验单条文档；通过返回 ``None``，否则返回拒绝原因。"""
    if not force:
        # 诚信红线①：必须人工审校（``reviewed_by`` 非空；``PENDING:`` 前缀允许入库但另标记）
        if review_state(row) == "unverified":
            return "reviewed_by 为空（未经人工审校）——拒绝入库【诚信红线】"
        # 诚信红线②：必须有 ≥1 个 A 级来源
        if not has_grade_a_source(row):
            return "sources 不含 A 级来源——拒绝入库【诚信红线】"
    # 数据完整性
    if not md_path.exists():
        return f"文档缺失：{md_path.as_posix()}"
    if not md_text or not md_text.strip():
        return "文档内容为空"
    return None


def run(args: argparse.Namespace) -> int:
    """入库主流程，返回退出码（0=全部通过；1=存在被拒文档）。"""
    rows = load_class_map()
    diseases_dir = settings.kb_diseases_path
    diseases_dir.mkdir(parents=True, exist_ok=True)

    # 目标集：默认取「kb/diseases/ 下已有文档」的类别；--slug 指定时按 slug 定向校验
    wanted = set(args.slug) if args.slug else None
    targets: list[tuple[dict, object]] = []
    all_docs = doc_rows(rows)
    for row in all_docs:
        md_path = diseases_dir / f"{row['slug']}.md"
        if wanted is not None:
            if row["slug"] in wanted:
                targets.append((row, md_path))
        elif md_path.exists():
            targets.append((row, md_path))

    if wanted is not None:
        found = {row["slug"] for row, _ in targets}
        for slug in sorted(wanted - found):
            print(f"  ✗ 未知 slug：{slug}（不在 kb/class-map.json 中）")

    imported: list[str] = []
    pending: list[str] = []
    rejected: list[tuple[str, str]] = []

    for row, md_path in targets:
        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else None
        reason = _validate(row, md_path, md_text, args.force)
        if reason:
            rejected.append((row["slug"], reason))
            continue
        imported.append(row["slug"])
        # 三态闸门：PENDING（团队代整理、用户尚未本人复核）允许入库，但必须醒目告警
        if not args.force and review_state(row) == "pending":
            pending.append(row["slug"])
            print(f"  ⚠ 未人工审校（PENDING），仅供演示：{row['slug']}")

    # 落库
    if not args.dry_run and imported:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models.knowledge import KnowledgeDoc

        db = SessionLocal()
        try:
            for row, md_path in targets:
                if row["slug"] not in imported:
                    continue
                rel_path = f"kb/diseases/{row['slug']}.md"
                md_text = md_path.read_text(encoding="utf-8")
                existing = db.scalar(
                    select(KnowledgeDoc).where(KnowledgeDoc.source_path == rel_path)
                )
                if existing is None:
                    db.add(KnowledgeDoc(
                        title=row["disease_cn"],
                        crop=row.get("crop_cn") or None,
                        disease=row["disease_cn"],
                        source_path=rel_path,
                        content_md=md_text,
                        vector_status="pending",
                    ))
                else:
                    existing.title = row["disease_cn"]
                    existing.crop = row.get("crop_cn") or None
                    existing.disease = row["disease_cn"]
                    existing.content_md = md_text
                    # 不改 vector_status：由 build_index 维护
            db.commit()
        finally:
            db.close()

    # 汇总输出
    mode = "（dry-run，未写库）" if args.dry_run else ""
    print(f"=== 入库{'校验' if args.dry_run else '完成'}{mode} ===")
    print(f"目标文档：{len(targets)}　通过：{len(imported)}　拒绝：{len(rejected)}")
    print(f"未审校（PENDING，仅演示）：{len(pending)} 篇")
    for slug in imported:
        tag = "⚠" if slug in pending else "✓"
        print(f"  {tag} {slug}")
    for slug, reason in rejected:
        print(f"  ✗ {slug} → {reason}")
    if pending:
        print(f"! 未审校 {len(pending)} 篇（PENDING·团队代整理、待用户本人复核）："
              f"{', '.join(pending)}")

    if rejected:
        print("! 存在被拒文档，未通过诚信红线校验；请回填 kb/class-map.json 的 "
              "reviewed_by/reviewed_at/sources 后重试。")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="知识库入库脚本（校验诚信红线后写库）")
    parser.add_argument("--dry-run", action="store_true", help="只校验，不写数据库")
    parser.add_argument("--force", action="store_true", help="跳过诚信校验（仅本地调试，慎用）")
    parser.add_argument("--slug", nargs="*", default=None, help="定向校验指定 slug 列表")
    return parser


def main() -> int:
    """命令行入口。"""
    args = build_parser().parse_args()
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 —— 顶层兜底
        print(f"入库脚本异常：{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
