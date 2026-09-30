# -*- coding: utf-8 -*-
"""``kb/class-map.json`` 加载工具（类名 → 中文名 / 作物中文名派生）。

设计依据：``docs/impl-pc-admin-v1.md`` §3.2 建议「把 ``class_name → 中文名`` 的派生
抽到公共位置供复用，前端不得复制映射表」。

单一事实来源为 ``kb/class-map.json``；文件缺失 / 损坏一律返回空索引（降级为原始类名），
**绝不抛错**（对齐「降级不抛错」原则）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from loguru import logger

from app.core.config import REPO_ROOT, settings


def class_map_path() -> Path:
    """``kb/class-map.json`` 的绝对路径（相对路径以仓库根为基准）。"""
    rel = getattr(settings, "kb_class_map_path", "kb/class-map.json") or "kb/class-map.json"
    path = Path(rel)
    return path if path.is_absolute() else (REPO_ROOT / path)


@lru_cache(maxsize=1)
def class_map_index() -> dict[str, dict]:
    """加载映射表 → ``{class_name: row}``（内存缓存）。

    文件缺失 / 解析失败返回空字典并记 warning，调用方按原始类名降级。
    """
    path = class_map_path()
    if not path.exists():
        logger.warning(f"class-map 不存在，中文名派生降级为原始类名：{path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"class-map 解析失败，中文名派生降级为原始类名：{exc}")
        return {}
    if not isinstance(raw, list):
        logger.warning(f"class-map 结构应为数组，实际 {type(raw).__name__}，降级")
        return {}
    index: dict[str, dict] = {}
    for row in raw:
        if isinstance(row, dict) and row.get("class_name"):
            index[str(row["class_name"])] = row
    return index


def disease_cn_of(class_name: str | None) -> str | None:
    """类名 → 病害中文名；缺失返回 ``None``。"""
    if not class_name:
        return None
    return class_map_index().get(class_name, {}).get("disease_cn")


def crop_cn_of(class_name: str | None) -> str | None:
    """类名 → 作物中文名；缺失返回 ``None``。"""
    if not class_name:
        return None
    return class_map_index().get(class_name, {}).get("crop_cn")


def crop_pairs() -> list[tuple[str, str]]:
    """返回映射表内 ``(crop_en, crop_cn)`` 去重列表（供门户作物分类聚合）。"""
    seen: dict[str, str] = {}
    for row in class_map_index().values():
        crop_en = str(row.get("crop_en") or "").strip()
        crop_cn = str(row.get("crop_cn") or "").strip()
        if crop_cn and crop_en not in seen:
            seen[crop_en] = crop_cn
    return sorted(seen.items(), key=lambda kv: kv[1])


__all__ = [
    "class_map_path",
    "class_map_index",
    "disease_cn_of",
    "crop_cn_of",
    "crop_pairs",
]
