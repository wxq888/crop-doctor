# -*- coding: utf-8 -*-
"""预警（warning）相关请求/响应模型。

契约见 ``docs/impl-pc-admin-v1.md`` §2.3 / §4。时间出参统一经 ``UtcDatetime``
序列化为 ISO-8601 带 ``Z``（复用 ``schemas/common.py``）。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

# 降雨条件 / 风险等级字面量
RainCondition = Literal["any", "rain", "no_rain"]
RiskLevel = Literal["high", "mid", "low"]


class RuleIn(BaseModel):
    """预警规则入参（病害 × 气象条件的爆发条件）。"""

    disease: str = Field(max_length=100, description="病害类名（模型原始类名）")
    crop: str | None = Field(default=None, max_length=50, description="作物（可选）")
    temp_min: float | None = Field(default=None, description="适宜最低温（℃），None 不约束")
    temp_max: float | None = Field(default=None, description="适宜最高温（℃），None 不约束")
    humidity_min: float | None = Field(default=None, description="最低湿度（%），None 不约束")
    humidity_max: float | None = Field(default=None, description="最高湿度（%），None 不约束")
    rain_condition: RainCondition = Field(default="any", description="any | rain | no_rain")
    risk_level: RiskLevel = Field(description="命中后生成的风险等级")
    advice: str | None = Field(default=None, max_length=500, description="防治建议文案")
    enabled: int = Field(default=1, ge=0, le=1, description="是否启用（1 启用 / 0 停用）")


class RuleOut(RuleIn):
    """预警规则出参（含主键与派生中文名）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    disease_cn: str | None = None
    crop_cn: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RuleUpdate(BaseModel):
    """预警规则局部更新入参（仅传入的字段被修改）。"""

    disease: str | None = Field(default=None, max_length=100)
    crop: str | None = Field(default=None, max_length=50)
    temp_min: float | None = None
    temp_max: float | None = None
    humidity_min: float | None = None
    humidity_max: float | None = None
    rain_condition: RainCondition | None = None
    risk_level: RiskLevel | None = None
    advice: str | None = Field(default=None, max_length=500)
    enabled: int | None = Field(default=None, ge=0, le=1)


class RefreshIn(BaseModel):
    """手动触发风险评估入参（``POST /warning/refresh``）。"""

    location: str | None = Field(default=None, max_length=50, description="位置，缺省用配置")


class AlertItem(BaseModel):
    """预警记录出参。"""

    id: int
    source: str = Field(description="weather | detection")
    disease: str
    disease_cn: str | None = None
    risk_level: str
    content: str
    location: str | None = None
    forecast_date: str | None = Field(default=None, description="YYYY-MM-DD")
    is_read: bool = False
    for_me: bool = Field(default=True, description="是否本人可见（全局广播或定向本人）")
    created_at: UtcDatetime


class WarningNowOut(BaseModel):
    """预警总览内嵌的实时天气。"""

    location: str | None = None
    text: str | None = None
    temp: float | None = None
    humidity: float | None = None
    wind_dir: str | None = None
    wind_scale: str | None = None
    updated_at: str | None = None


class WarningForecastDayOut(BaseModel):
    """预警总览内嵌的单日预报。"""

    date: str
    temp_max: float
    temp_min: float
    text_day: str
    text_night: str
    humidity: float | None = None
    precip: float | None = None


class WarningRiskItem(BaseModel):
    """当前生效风险条目（用于总览「当前风险」列表）。"""

    disease: str
    disease_cn: str | None = None
    risk_level: str
    forecast_date: str
    advice: str | None = None


class WarningStats(BaseModel):
    """风险等级计数。"""

    high: int = 0
    mid: int = 0
    low: int = 0


class WarningOverview(BaseModel):
    """预警中心总览出参。"""

    degraded: bool
    location: str | None = None
    now: WarningNowOut | None = None
    forecast: list[WarningForecastDayOut] = Field(default_factory=list)
    current_risks: list[WarningRiskItem] = Field(default_factory=list)
    stats: WarningStats = Field(default_factory=WarningStats)
    last_refresh_at: str | None = None


class RiskEvaluation(BaseModel):
    """一次风险评估结果出参（``POST /warning/refresh``）。"""

    degraded: bool
    location: str | None = None
    evaluated_rules: int = 0
    matched: int = 0
    created: int = 0
    alerts: list[AlertItem] = Field(default_factory=list)


class UnreadCountOut(BaseModel):
    """未读计数出参。"""

    count: int = 0


__all__ = [
    "RainCondition",
    "RiskLevel",
    "RuleIn",
    "RuleOut",
    "RuleUpdate",
    "AlertItem",
    "WarningNowOut",
    "WarningForecastDayOut",
    "WarningRiskItem",
    "WarningStats",
    "WarningOverview",
    "RiskEvaluation",
    "UnreadCountOut",
]
