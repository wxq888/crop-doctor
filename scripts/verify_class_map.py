# -*- coding: utf-8 -*-
"""类名映射表校验：``kb/class-map.json`` 与评测报告逐字比对 + 结构核对。

用途（T01 验收标准 #1）：确认 38 个 ``doc_type != 'ignore'`` 类的 ``class_name``
与 ``ml/exports/eval-report-yolo11s-plantvillage38-v1.txt`` **逐字一致**（含空格/逗号/原始拼写），
并核对病原类别分布（真菌17·细菌3·卵菌2·病毒2·虫害1·检疫性1·健康12）。

用法（在仓库根执行）::

    .venv\\Scripts\\python.exe scripts\\verify_class_map.py
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from kb_common import CATEGORY_ENUM, REPO_ROOT, doc_rows, load_class_map

REPORT_PATH = REPO_ROOT / "ml" / "exports" / "eval-report-yolo11s-plantvillage38-v1.txt"

# 期望的病原类别分布
EXPECTED_CATEGORIES = {"真菌": 17, "细菌": 3, "卵菌": 2, "病毒": 2, "虫害": 1, "检疫性": 1, "健康": 12}


def parse_report_names(path: Path) -> list[str]:
    """从评测报告抽取类名（行首到「正确」之间的部分）。"""
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(.+?)\s{2,}正确\s", line)
        if m:
            names.append(m.group(1).rstrip())
    return names


def main() -> int:
    """执行校验并打印结果；零差异返回 0，否则返回 1。"""
    rows = load_class_map()
    map_names = [r["class_name"] for r in rows]
    report_names = parse_report_names(REPORT_PATH)
    report_no_bg = [n for n in report_names if n != "Background_without_leaves"]
    map_no_bg = [n for n in map_names if n != "Background_without_leaves"]

    ok = True
    print(f"class-map 行数：{len(map_names)}（应为 39）")
    print(f"评测报告行数：{len(report_names)}")
    if len(map_names) != 39:
        ok = False
        print("  ✗ 行数不为 39")
    if set(map_names) != set(report_names):
        ok = False
        print("  ✗ 类名集合不一致")
        print("    仅 map 有的：", sorted(set(map_names) - set(report_names)))
        print("    仅 report 有的：", sorted(set(report_names) - set(map_names)))
    else:
        print("  ✓ 类名集合与评测报告一致")
    if report_no_bg == map_no_bg:
        print("  ✓ 去背景类后顺序逐字一致（含空格/逗号/原始拼写）")
    else:
        ok = False
        print("  ✗ 顺序逐字比对存在差异")
        for i, (a, b) in enumerate(zip(report_no_bg, map_no_bg)):
            if a != b:
                print(f"    @{i}: {a!r} != {b!r}")

    # 结构核对
    docs = doc_rows(rows)
    print(f"doc_type != ignore 的行数：{len(docs)}（应为 38）")
    if len(docs) != 38:
        ok = False
        print("  ✗ 非忽略行数不为 38")
    cats = Counter(r["category"] for r in rows if r["doc_type"] != "ignore")
    actual = {k: cats.get(k, 0) for k in EXPECTED_CATEGORIES}
    print(f"病原类别分布：{actual}")
    if actual == EXPECTED_CATEGORIES:
        print("  ✓ 类别分布核对通过（真菌17·细菌3·卵菌2·病毒2·虫害1·检疫性1·健康12）")
    else:
        ok = False
        print(f"  ✗ 类别分布不符，期望 {EXPECTED_CATEGORIES}")
    bad_enum = [r["class_name"] for r in rows if r["category"] not in CATEGORY_ENUM]
    if bad_enum:
        ok = False
        print("  ✗ 非法 category：", bad_enum)

    # 关键易错类名
    probes = [
        "Corn___Cercospora_leaf_spot Gray_leaf_spot",
        "Pepper,_bell___Bacterial_spot",
        "Tomato___Spider_mites Two-spotted_spider_mite",
        "Orange___Haunglongbing_(Citrus_greening)",
        "Grape___Esca_(Black_Measles)",
        "Grape___Leaf_blight_(Isariopsis_Leaf_Spot)",
        "Tomato___Tomato_Yellow_Leaf_Curl_Virus",
        "Tomato___Tomato_mosaic_virus",
    ]
    for probe in probes:
        present = probe in map_names
        ok = ok and present
        print(f"  [{'✓' if present else '✗'}] {probe!r}")

    print("\nRESULT:", "ZERO_DIFF / PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
