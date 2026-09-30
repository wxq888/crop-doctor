# -*- coding: utf-8 -*-
"""天气接口：实时 / 预报（1~7 天）/ 24h 逐时 / 施药建议（均支持降级，永不 500）。"""
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.response import ok
from app.schemas.weather import (
    DailyForecastOut,
    ForecastOut,
    HourlyForecastOut,
    HourlyOut,
    NowWeatherOut,
    SprayAdviceOut,
)
from app.services.weather import weather_service

router = APIRouter()


@router.get("/now", summary="实时天气")
async def get_now(
    location: Annotated[str | None, Query(max_length=50, description="位置（缺省用配置）")] = None,
) -> dict:
    """返回实时天气（含体感/降水/气压/能见度/云量/露点）；数据不可用时 ``degraded=true`` 且字段为 null。"""
    data = await weather_service.get_now(location)
    if data is None:
        return ok(NowWeatherOut(degraded=True))
    return ok(NowWeatherOut(**asdict(data), degraded=False))


@router.get("/forecast", summary="未来 N 天预报（1~7 天）")
async def get_forecast(
    location: Annotated[str | None, Query(max_length=50, description="位置（缺省用配置）")] = None,
    days: Annotated[int, Query(ge=1, le=7, description="预报天数（≤3 走 3d 接口，>3 走 7d 接口）")] = 3,
) -> dict:
    """返回未来 N 天预报；数据不可用时 ``list=[]`` 且 ``degraded=true``。"""
    items = await weather_service.get_forecast(location, days)
    if not items:
        return ok(ForecastOut(list=[], degraded=True))
    return ok(
        ForecastOut(
            list=[DailyForecastOut(**asdict(item)) for item in items],
            degraded=False,
        )
    )


@router.get("/hourly", summary="未来 24 小时逐时预报")
async def get_hourly(
    location: Annotated[str | None, Query(max_length=50, description="位置（缺省用配置）")] = None,
) -> dict:
    """返回未来 24 小时逐时预报（含降水概率 pop）；数据不可用时 ``list=[]`` 且 ``degraded=true``。"""
    items = await weather_service.get_hourly(location)
    if not items:
        return ok(HourlyOut(list=[], degraded=True))
    return ok(
        HourlyOut(
            list=[HourlyForecastOut(**asdict(item)) for item in items],
            degraded=False,
        )
    )


@router.get("/spray-advice", summary="施药时机建议")
async def get_spray_advice(
    location: Annotated[str | None, Query(max_length=50, description="位置（缺省用配置）")] = None,
) -> dict:
    """结合未来预报给出施药时机建议；无天气数据时降级文案。"""
    advice = await weather_service.get_spray_advice(location)
    return ok(SprayAdviceOut(**asdict(advice)))
