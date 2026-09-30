# -*- coding: utf-8 -*-
"""严重度分级引擎（纯规则）。

阈值读取 ``settings``（源自 ``.env``），纯函数无副作用，便于单测与答辩解释。
"""
from app.core.config import settings

# 级别 → 中文标签
SEVERITY_LABELS: dict[int, str] = {0: "无", 1: "轻微", 2: "中等", 3: "严重"}


def grade(spot_count: int, area_ratio: float) -> int:
    """按病斑框数与面积占比给出 0/1/2/3 级别。

    规则（与设计文档 §4.2 一致）：
    - ``spot_count <= 0`` → 0（未检出）；
    - 面积占比达到 severe/moderate 阈值 → 3 / 2；
    - 病斑数达到 moderate/minor 阈值 → 2 / 1；
    - 两者取较大值；检出但未达任一阈值时至少为 1（轻微）。
    """
    if spot_count <= 0:
        return 0

    score = 0
    if area_ratio >= settings.severity_area_ratio_severe:
        score = max(score, 3)
    elif area_ratio >= settings.severity_area_ratio_moderate:
        score = max(score, 2)

    if spot_count >= settings.severity_spot_count_moderate:
        score = max(score, 2)
    elif spot_count >= settings.severity_spot_count_minor:
        score = max(score, 1)

    if score == 0:
        score = 1  # 检出即至少"轻微"
    return score


def label_of(level: int) -> str:
    """级别 → 中文标签；未知级别返回"未知"。"""
    return SEVERITY_LABELS.get(level, "未知")


__all__ = ["SEVERITY_LABELS", "grade", "label_of"]
