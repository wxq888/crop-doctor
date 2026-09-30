# -*- coding: utf-8 -*-
"""多条件叠加提权定级测试（方案 B）：四维齐全才判 high，否则降级。

覆盖四种核心场景：
① 四维齐全且全中 → 保留原级别
② 声明三维 → 降一级（high→mid）
③ 声明二维 → 降一级（mid→low）
④ 原 low 且声明不全 → 降级低于 low，不生成
外加：回退开关 ``WARNING_REQUIRE_FULL_DIMENSIONS=false``、文案透明性、
``low`` 四维齐全仍保留 low、``matched`` 兼容旧语义。
"""
import pytest

from app.core.config import settings
from app.models.warning import DiseaseWeatherRule
from app.services.weather import DailyForecast
from app.services.weather_risk import (
    _declared_dimensions,
    _grade_level,
    weather_risk_engine,
)


def _rule(**kw) -> DiseaseWeatherRule:
    """构造未入库的规则对象（纯定级 / 匹配测试用）。"""
    rule = DiseaseWeatherRule(
        disease=kw.get("disease", "Tomato___Late_blight"),
        crop=kw.get("crop", "Tomato"),
        temp_min=kw.get("temp_min"),
        temp_max=kw.get("temp_max"),
        humidity_min=kw.get("humidity_min"),
        humidity_max=kw.get("humidity_max"),
        rain_condition=kw.get("rain_condition", "any"),
        risk_level=kw.get("risk_level", "high"),
        advice=kw.get("advice", None),
        enabled=1,
    )
    rule.id = kw.get("id", 1)
    return rule


def _day(**kw) -> DailyForecast:
    """构造单日预报（默认 18~22℃ / RH85% / 中雨，与需求桩一致）。"""
    return DailyForecast(
        date=kw.get("date", "2026-09-18"),
        temp_max=kw.get("temp_max", 22.0),
        temp_min=kw.get("temp_min", 18.0),
        text_day=kw.get("text_day", "中雨"),
        text_night=kw.get("text_night", "小雨"),
        humidity=kw.get("humidity", 85.0),
        precip=kw.get("precip", 8.0),
    )


def _dim_count(rule: DiseaseWeatherRule) -> int:
    """规则声明的维度数。"""
    return sum(1 for v in _declared_dimensions(rule).values() if v)


# ============================================================
# ① 四维齐全且全中 → 保留原级别
# ============================================================
def test_full_dimensions_preserves_original_level(monkeypatch) -> None:
    """四维（温度·湿度·降雨·作物）齐全且全中 → 保留规则原级别。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        temp_min=18.0, temp_max=22.0, humidity_min=75.0,
        rain_condition="rain", crop="Tomato", risk_level="high",
    )
    assert _dim_count(rule) == 4
    assert _grade_level(rule)[0] == "high"

    hit = weather_risk_engine.match_rule(rule, _day())
    assert hit is not None
    assert hit.risk_level == "high"  # 四维齐全 → 保留原级别
    assert "四维条件同时满足" in hit.content
    assert "高爆发风险" in hit.content


@pytest.mark.parametrize("level", ["high", "mid", "low"])
def test_full_dimensions_preserve_each_level(monkeypatch, level: str) -> None:
    """四维齐全时 high / mid / low 均原样保留（含 low 仍生成）。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        temp_min=18.0, temp_max=22.0, humidity_min=75.0,
        rain_condition="rain", crop="Tomato", risk_level=level,
    )
    hit = weather_risk_engine.match_rule(rule, _day())
    assert hit is not None and hit.risk_level == level


# ============================================================
# ② 声明三维 → 降一级
# ============================================================
def test_three_dimensions_downgrade_high_to_mid(monkeypatch) -> None:
    """声明三维（缺湿度）→ high 降为 mid，文案带降级依据。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        temp_min=17.0, temp_max=20.0, humidity_min=None, humidity_max=None,
        rain_condition="rain", crop="Apple", risk_level="high",
    )
    assert _dim_count(rule) == 3
    assert _grade_level(rule)[0] == "mid"

    hit = weather_risk_engine.match_rule(rule, _day())  # 18~22℃ 有雨，命中 17~20℃
    assert hit is not None
    assert hit.risk_level == "mid"
    assert "三维条件" in hit.content
    assert "未声明湿度" in hit.content
    assert "风险由高降为中" in hit.content
    assert "中爆发风险" in hit.content and "高爆发风险" not in hit.content


def test_three_dimensions_downgrade_mid_to_low(monkeypatch) -> None:
    """声明三维的 mid 规则 → 降为 low。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        temp_min=17.0, temp_max=20.0, humidity_min=None, humidity_max=None,
        rain_condition="rain", crop="Tomato", risk_level="mid",
    )
    assert _dim_count(rule) == 3
    hit = weather_risk_engine.match_rule(rule, _day())
    assert hit is not None and hit.risk_level == "low"


# ============================================================
# ③ 声明二维 → 降一级
# ============================================================
def test_two_dimensions_downgrade_mid_to_low(monkeypatch) -> None:
    """声明二维（湿度 + 降雨，无作物）→ mid 降为 low。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        disease="Grape___Leaf_blight", crop=None,
        temp_min=None, temp_max=None, humidity_min=85.0,
        rain_condition="rain", risk_level="mid",
    )
    assert _dim_count(rule) == 2
    assert _grade_level(rule)[0] == "low"

    hit = weather_risk_engine.match_rule(rule, _day(humidity=85.0))
    assert hit is not None
    assert hit.risk_level == "low"
    assert "两维条件" in hit.content
    assert "风险由中降为低" in hit.content


# ============================================================
# ④ 原 low 且声明不全 → 不生成
# ============================================================
def test_low_with_incomplete_dims_not_generated(monkeypatch) -> None:
    """原级别 low 且声明不全 → 降级低于 low，返回 None（不生成该预警）。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        disease="Grape___Leaf_blight", crop=None,
        temp_min=None, temp_max=None, humidity_min=85.0,
        rain_condition="rain", risk_level="low",
    )
    assert _dim_count(rule) == 2
    assert _grade_level(rule)[0] is None  # low 再降 → 低于 low
    assert weather_risk_engine.match_rule(rule, _day(humidity=85.0)) is None


# ============================================================
# 回退开关：false → 完全回退旧行为（命中即按原级别）
# ============================================================
def test_switch_off_restores_original_behavior(monkeypatch) -> None:
    """WARNING_REQUIRE_FULL_DIMENSIONS=false → 不降级，low 也不丢弃。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", False)

    three_dim_high = _rule(
        temp_min=17.0, temp_max=20.0, humidity_min=None, humidity_max=None,
        rain_condition="rain", crop="Apple", risk_level="high",
    )
    hit = weather_risk_engine.match_rule(three_dim_high, _day())
    assert hit is not None and hit.risk_level == "high"  # 旧行为：原级别

    two_dim_low = _rule(
        disease="Grape___Leaf_blight", crop=None,
        temp_min=None, temp_max=None, humidity_min=85.0,
        rain_condition="rain", risk_level="low",
    )
    hit2 = weather_risk_engine.match_rule(two_dim_low, _day(humidity=85.0))
    assert hit2 is not None and hit2.risk_level == "low"  # 旧行为：不丢弃

    # 回退时也不带「降级」尾注
    assert "降为" not in hit.content and "降为" not in hit2.content


def test_default_config_is_true() -> None:
    """配置默认值：多条件叠加提权默认开启。"""
    assert settings.warning_require_full_dimensions is True


# ============================================================
# 兼容 / 透明性
# ============================================================
def test_matched_keys_backward_compatible(monkeypatch) -> None:
    """``matched`` 兼容旧语义（temp/humidity/rain）并新增 crop。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        temp_min=18.0, temp_max=22.0, humidity_min=75.0,
        rain_condition="rain", crop="Tomato", risk_level="high",
    )
    hit = weather_risk_engine.match_rule(rule, _day(humidity=None))
    assert hit is not None
    assert hit.matched["temp"] is True
    assert hit.matched["humidity"] is False  # 声明了但当日缺数据 → 旧语义保持
    assert hit.matched["rain"] is True
    assert hit.matched["crop"] is True


def test_content_within_length_limit(monkeypatch) -> None:
    """超长 advice 时文案仍截断至 500 字内。"""
    monkeypatch.setattr(settings, "warning_require_full_dimensions", True)
    rule = _rule(
        temp_min=18.0, temp_max=22.0, humidity_min=75.0,
        rain_condition="rain", crop="Tomato", risk_level="high",
        advice="药" * 800,
    )
    hit = weather_risk_engine.match_rule(rule, _day())
    assert hit is not None
    assert len(hit.content) <= 500
