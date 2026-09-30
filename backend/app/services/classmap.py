# -*- coding: utf-8 -*-
"""类名 → 中文名派生（复用 ``kb/class-map.json``）。

设计依据：``docs/impl-pc-admin-v1.md`` §3.2（``disease_cn`` / ``crop_cn`` 由后端派生，
前端不得复制映射表）。

与 ``api/v1/chat.py::_class_map_index`` 同源：``class-map.json`` 为唯一事实来源；
文件缺失 / 损坏一律降级为「原始类名」，绝不抛错（对齐「降级不抛错」原则）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from loguru import logger

from app.core.config import REPO_ROOT, settings


def _class_map_path() -> Path:
    """``kb/class-map.json`` 的绝对路径（相对路径以仓库根为基准）。"""
    rel = getattr(settings, "kb_class_map_path", "kb/class-map.json") or "kb/class-map.json"
    path = Path(rel)
    return path if path.is_absolute() else (REPO_ROOT / path)


@lru_cache(maxsize=1)
def class_map_index() -> dict[str, dict]:
    """加载 ``kb/class-map.json`` → ``{class_name: row}``（内存缓存）。"""
    path = _class_map_path()
    if not path.exists():
        logger.warning(f"class-map 不存在，中文名派生降级为原始类名：{path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"class-map 解析失败，中文名派生降级为原始类名：{exc}")
        return {}

    index: dict[str, dict] = {}
    for row in raw if isinstance(raw, list) else []:
        if isinstance(row, dict) and row.get("class_name"):
            index[str(row["class_name"])] = row
    return index


def reload_class_map() -> None:
    """清空内存缓存（知识库扩容后热更用；非必需）。"""
    class_map_index.cache_clear()


def row_of(class_name: str | None) -> dict:
    """返回某类名对应的映射行；缺失返回空字典。"""
    return class_map_index().get(class_name or "", {})


def disease_cn_of(class_name: str | None) -> str | None:
    """类名 → 病害中文名；缺失回退原始类名（无类名则 None）。"""
    row = row_of(class_name)
    return row.get("disease_cn") or class_name


def crop_cn_of(class_name: str | None) -> str | None:
    """类名 → 作物中文名；缺失回退类名前缀。"""
    row = row_of(class_name)
    if row.get("crop_cn"):
        return row["crop_cn"]
    return derive_crop(class_name)


def crop_cn_by_en(crop_en: str | None) -> str | None:
    """作物英文名 → 作物中文名（由 class-map 反查）；缺失回退原值。"""
    if not crop_en:
        return None
    for row in class_map_index().values():
        if row.get("crop_en") == crop_en and row.get("crop_cn"):
            return row["crop_cn"]
    return crop_en


def derive_crop(class_name: str | None) -> str | None:
    """由类名派生作物名（如 ``Apple___Apple_scab`` → ``Apple``）。"""
    if not class_name:
        return None
    if "___" in class_name:
        return class_name.split("___")[0]
    return class_name.split("_")[0] if "_" in class_name else class_name


__all__ = [
    "class_map_index",
    "reload_class_map",
    "row_of",
    "disease_cn_of",
    "crop_cn_of",
    "crop_cn_by_en",
    "derive_crop",
]
