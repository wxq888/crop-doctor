# -*- coding: utf-8 -*-
"""严重度分级引擎单测（纯函数）。

除基础档位外，重点覆盖：
- **阈值边界值本身**（``>=`` 为闭区间，边界必须归入更高档）；
- **阈值确实读自 settings（.env）**（改配置即改结果），杜绝"硬编码常量"。
"""
import pytest

from app.core.config import settings
from app.services.severity import SEVERITY_LABELS, grade, label_of


# ------------------------------------------------------------
# 基础档位
# ------------------------------------------------------------
def test_grade_zero_when_no_spot() -> None:
    """无病斑 → 0。"""
    assert grade(0, 0.0) == 0
    assert grade(-1, 0.5) == 0


def test_grade_minor_when_detected_but_small() -> None:
    """检出但面积极小/数量少 → 至少 1（轻微）。"""
    assert grade(1, 0.0) == 1
    assert grade(1, 0.01) == 1


def test_grade_moderate_by_count() -> None:
    """病斑数达 moderate 阈值 → 2。"""
    assert grade(5, 0.0) == 2


def test_grade_moderate_by_area() -> None:
    """面积占比达 moderate 阈值 → 2。"""
    assert grade(2, 0.06) == 2


def test_grade_severe_by_area() -> None:
    """面积占比达 severe 阈值 → 3。"""
    assert grade(1, 0.2) == 3
    assert grade(8, 0.9) == 3


def test_label_of() -> None:
    """级别标签映射。"""
    assert label_of(0) == "无"
    assert label_of(1) == "轻微"
    assert label_of(2) == "中等"
    assert label_of(3) == "严重"
    assert label_of(99) == "未知"
    assert SEVERITY_LABELS[3] == "严重"


# ------------------------------------------------------------
# 边界值（默认阈值：minor=2 / moderate=5 / area_moderate=0.05 / area_severe=0.15）
# ------------------------------------------------------------
@pytest.mark.parametrize(
    ("spot_count", "area_ratio", "expected"),
    [
        (0, 0.99, 0),          # spot<=0 一律 0，面积再大也是 0
        (1, 0.049, 1),         # 面积未达 0.05 且仅 1 框 → 兜底轻微
        (1, 0.05, 2),          # 面积恰好等于 moderate 边界（闭区间）→ 2
        (1, 0.059, 2),
        (1, 0.15, 3),          # 面积恰好等于 severe 边界（闭区间）→ 3
        (4, 0.0, 1),           # 2<=4<5 且面积未达 → 1
        (5, 0.0, 2),           # 框数恰好等于 moderate 边界 → 2
        (2, 0.0, 1),           # 框数恰好等于 minor 边界 → 1
        (5, 0.15, 3),          # 面积 severe 压过 → 3
        (8, 0.05, 2),          # 面积 moderate + 框数 moderate → 2
    ],
)
def test_grade_threshold_boundaries(spot_count: int, area_ratio: float, expected: int) -> None:
    """阈值边界值本身（``>=`` 语义）逐条校验。"""
    assert grade(spot_count, area_ratio) == expected


def test_grade_reads_thresholds_from_settings(monkeypatch) -> None:
    """阈值确实取自 settings：调高阈值后同一输入应降级。"""
    monkeypatch.setattr(settings, "severity_spot_count_minor", 10)
    monkeypatch.setattr(settings, "severity_spot_count_moderate", 20)
    monkeypatch.setattr(settings, "severity_area_ratio_moderate", 0.50)
    monkeypatch.setattr(settings, "severity_area_ratio_severe", 0.90)

    # 默认阈值下 grade(5, 0.05) == 2；阈值调高后不再达标 → 兜底 1
    assert grade(5, 0.05) == 1
    # 面积达到新的 severe 阈值 → 3
    assert grade(1, 0.95) == 3
