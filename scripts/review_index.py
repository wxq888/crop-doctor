# -*- coding: utf-8 -*-
"""生成批量审校索引 ``kb/_review/REVIEW-INDEX.md``。

数据来源（均为脚本只读）：
  * ``kb/_review/report.json`` —— ``scripts/collect_kb.py`` 采集报告（每类来源数 / A 级数 / 逐源抽取字数）；
  * ``kb/class-map.json``      —— 类名 / 中文病害名 / 作物 / 类别 映射。

输出表格列：
  序号 · 类名(class_name) · 中文病害名 · 作物 · 类别 · 草稿文件(相对路径) ·
  抓到来源数 · A级来源数 · 正文抽字数 · 状态(✅充实/⚠️偏少/❌未抓到) · 备注

状态判定：
  * 抓到来源数 == 0            → ``❌未抓到``；
  * 正文抽字数 ≥ ``RICH_MIN``  → ``✅充实``；
  * 其余                        → ``⚠️偏少``。

用法（仓库根）::

    .venv\\Scripts\\python.exe scripts\\review_index.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
REPORT_PATH: Path = REPO_ROOT / "kb" / "_review" / "report.json"
CLASS_MAP_PATH: Path = REPO_ROOT / "kb" / "class-map.json"
OUT_PATH: Path = REPO_ROOT / "kb" / "_review" / "REVIEW-INDEX.md"

# 「✅充实」所需的最小正文中文字数（低于此判为「⚠️偏少」）
RICH_MIN: int = 600

STATUS_RICH = "✅充实"
STATUS_THIN = "⚠️偏少"
STATUS_MISS = "❌未抓到"


def _load_json(path: Path) -> object:
    """读取 UTF-8 JSON；缺失即抛错（索引依赖真实采集报告）。"""
    if not path.exists():
        raise FileNotFoundError(f"缺少文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _status(source_count: int, zh_chars: int) -> str:
    """按来源数 + 正文中文字数给出状态。"""
    if source_count <= 0:
        return STATUS_MISS
    if zh_chars >= RICH_MIN:
        return STATUS_RICH
    return STATUS_THIN


def _healthy_note(category: str, doc_type: str) -> str:
    """健康类特别备注（模板 E：无「防治方法」节，采集面向健康栽培/识别/相似病害）。"""
    if category == "健康" or doc_type == "healthy":
        return "健康类·模板E（无防治节；关键词=健康栽培/识别/相似病害）"
    return ""


def build() -> str:
    """组装 REVIEW-INDEX.md 文本。"""
    report = _load_json(REPORT_PATH)
    rows = _load_json(CLASS_MAP_PATH)
    assert isinstance(report, dict) and isinstance(rows, list)

    meta_by_slug: dict[str, dict] = {
        row.get("slug", ""): row for row in rows if row.get("slug")
    }
    classes: list[dict] = report.get("classes", [])
    totals = report.get("totals", {})

    lines: list[str] = []
    lines.append("# 知识库采集 · 批量审校索引")
    lines.append("")
    gen_at = report.get("generated_at", "")
    lines.append(f"> 采集报告生成时间：`{gen_at}`　|　索引生成："
                 f"`{datetime.now(timezone.utc).isoformat(timespec='seconds')}`")
    lines.append("> **本索引仅登记「待审校草稿」，草稿不入库、不直接采用**。"
                 "审校通过后回填 `kb/class-map.json` 的 `reviewed_by/reviewed_at/sources`，"
                 "再由 `ingest_kb.py` 三态闸门入库。")
    lines.append("> 状态口径：`✅充实`=有来源且正文中文字数≥"
                 f"`{RICH_MIN}`；`⚠️偏少`=有来源但字数不足；`❌未抓到`=0 来源。")
    lines.append("")

    header = ("| 序号 | 类名(class_name) | 中文病害名 | 作物 | 类别 | 草稿文件 | "
              "抓到来源数 | A级来源数 | 正文抽字数 | 状态 | 备注 |")
    sep = "|---:|---|---|---|---|---|---:|---:|---:|---|---|"
    lines.append(header)
    lines.append(sep)

    n_rich = n_thin = n_miss = 0
    thin_list: list[str] = []
    miss_list: list[str] = []

    for idx, cls in enumerate(classes, start=1):
        slug = cls.get("slug", "")
        meta = meta_by_slug.get(slug, {})
        class_name = cls.get("class_name") or meta.get("class_name", "")
        disease_cn = cls.get("disease_cn") or meta.get("disease_cn", "")
        crop_cn = meta.get("crop_cn", "") or ""
        category = cls.get("category") or meta.get("category", "")
        doc_type = meta.get("doc_type", "")
        draft = cls.get("draft", "")
        src_count = int(cls.get("source_count", 0))
        a_count = int(cls.get("a_grade_count", 0))
        zh_chars = sum(int(s.get("zh_chars", 0)) for s in (cls.get("sources") or []))
        status = _status(src_count, zh_chars)
        note = _healthy_note(category, doc_type)

        if status == STATUS_RICH:
            n_rich += 1
        elif status == STATUS_THIN:
            n_thin += 1
            thin_list.append(f"{disease_cn}（`{slug}`，{zh_chars}字）")
        else:
            n_miss += 1
            miss_list.append(f"{disease_cn}（`{slug}`）")

        lines.append(
            f"| {idx} | `{class_name}` | {disease_cn} | {crop_cn} | {category} | "
            f"`{draft}` | {src_count} | {a_count} | {zh_chars} | {status} | {note} |"
        )

    # ---------------- 末尾汇总 ----------------
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append(f"- 采集类数：**{totals.get('classes', len(classes))}**"
                 f"（候选 URL {totals.get('unique_urls', '?')} 个，"
                 f"抓取成功 {totals.get('fetched', '?')}，"
                 f"失败 {totals.get('failed', '?')}，"
                 f"robots 跳过 {totals.get('skipped_robots', '?')}）")
    lines.append(f"- 状态分布：✅充实 **{n_rich}** 篇；⚠️偏少 **{n_thin}** 篇；❌未抓到 **{n_miss}** 篇")
    lines.append("")
    if thin_list:
        lines.append(f"- ⚠️偏少（{len(thin_list)}）：" + "、".join(thin_list))
    else:
        lines.append("- ⚠️偏少（0）：无")
    if miss_list:
        lines.append(f"- ❌未抓到（{len(miss_list)}）：" + "、".join(miss_list))
    else:
        lines.append("- ❌未抓到（0）：无")
    lines.append("")
    lines.append("> 说明：`⚠️偏少` 多为单一短页（如病虫情报）或整篇栽培方案中仅一段涉及该病害，"
                 "审校时建议补充 2–3 个 A 级来源后再撰写分节正文。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """命令行入口：写出 REVIEW-INDEX.md 并打印摘要。"""
    text = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"已写出：{OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
