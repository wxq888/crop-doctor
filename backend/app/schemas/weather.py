# -*- coding: utf-8 -*-
"""天气相关 Schema。"""
from pydantic import BaseModel, Field


class NowWeatherOut(BaseModel):
    """实时天气出参；降级时各字段为 null 且 ``degraded=true``。"""

    location: str | None = None
    text: str | None = None
    temp: float | None = None
    humidity: float | None = None
    wind_dir: str | None = None
    wind_scale: str | None = None
    updated_at: str | None = None
    # —— 天气详情页扩展字段（和风 now 原始字段映射；旧缓存/降级时为 None，向后兼容） ——
    feels_like: float | None = None  # 体感温度（℃）
    precip: float | None = None  # 当前小时降水量（mm）
    pressure: float | None = None  # 气压（hPa）
    vis: float | None = None  # 能见度（km）
    cloud: float | None = None  # 云量（%）
    dew: float | None = None  # 露点温度（℃）
    obs_time: str | None = None  # 观测时间（和风原始 obsTime）
    degraded: bool = False


class DailyForecastOut(BaseModel):
    """单日预报出参。"""

    date: str
    temp_max: float
    temp_min: float
    text_day: str
    text_night: str
    humidity: float | None = None
    precip: float | None = None


class HourlyForecastOut(BaseModel):
    """单小时预报出参（24h 接口）。"""

    fx_time: str
    temp: float
    text: str
    humidity: float | None = None
    precip: float | None = None
    pop: float | None = None  # 降水概率（%）
    wind_dir: str | None = None
    wind_scale: str | None = None


# 模块级别名：避免字段名 list 遮蔽内建 list 导致注解解析失败
DailyForecastList = list[DailyForecastOut]
HourlyForecastList = list[HourlyForecastOut]


class HourlyOut(BaseModel):
    """24 小时逐时预报出参；降级时 ``list=[]`` 且 ``degraded=true``。"""

    list: HourlyForecastList = Field(default_factory=list)
    degraded: bool = False


class ForecastOut(BaseModel):
    """预报列表出参；降级时 ``list=[]`` 且 ``degraded=true``。"""

    list: DailyForecastList = Field(default_factory=list)
    degraded: bool = False


class SprayAdviceOut(BaseModel):
    """施药建议出参。"""

    advice: str
    next_rain_date: str | None = None
    degraded: bool = False


__all__ = [
    "NowWeatherOut",
    "DailyForecastOut",
    "ForecastOut",
    "HourlyForecastOut",
    "HourlyOut",
    "SprayAdviceOut",
]
