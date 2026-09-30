# -*- coding: utf-8 -*-
"""和风天气服务：实时 / 预报（3d / 7d）/ 24h 逐时代理 + Redis 缓存 + 失败降级 + 施药建议。

降级策略（绝不向调用方抛异常）：
- 未配置 ``WEATHER_API_KEY``：不发起请求，直接降级；
- httpx 超时 / 非 200 / 解析失败：记 ``warning`` 日志，返回 ``None`` / ``[]`` / 降级建议。
"""
import json
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.core.redis_client import get_redis

_REQUEST_TIMEOUT = 5.0
_RAIN_KEYWORDS = ("雨", "雪", "雷")
_HOURLY_CACHE_TTL = 1800  # 24h 逐时预报缓存（秒）


def make_client() -> httpx.AsyncClient:
    """构造 httpx 异步客户端（独立函数便于测试注入 MockTransport）。"""
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)


@dataclass
class NowWeather:
    """实时天气。"""

    location: str
    text: str
    temp: float
    humidity: float
    wind_dir: str
    wind_scale: str
    updated_at: str
    # —— 天气详情页扩展字段（和风原始字段；缺失时为 None，向后兼容旧缓存） ——
    feels_like: float | None = None
    precip: float | None = None
    pressure: float | None = None
    vis: float | None = None
    cloud: float | None = None
    dew: float | None = None
    obs_time: str | None = None


@dataclass
class DailyForecast:
    """单日预报。"""

    date: str
    temp_max: float
    temp_min: float
    text_day: str
    text_night: str
    humidity: float | None = None
    precip: float | None = None


@dataclass
class HourlyForecast:
    """单小时预报（24h 接口）。"""

    fx_time: str
    temp: float
    text: str
    humidity: float | None = None
    precip: float | None = None
    pop: float | None = None
    wind_dir: str | None = None
    wind_scale: str | None = None


@dataclass
class SprayAdvice:
    """施药时机建议。"""

    advice: str
    next_rain_date: str | None = None
    degraded: bool = False


def _to_float(value: Any, default: float = 0.0) -> float:
    """宽松数值转换（和风字段均为字符串）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_float(value: Any) -> float | None:
    """宽松可空数值转换：缺失/非法 → None（保持降级语义，不虚造 0 值）。"""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_rainy(forecast: "DailyForecast | dict") -> bool:
    """判断某日是否有降雨/降雪/雷。"""
    if isinstance(forecast, DailyForecast):
        text = forecast.text_day + forecast.text_night
        precip = forecast.precip or 0.0
    else:
        text = str(forecast.get("textDay", "")) + str(forecast.get("textNight", ""))
        precip = _to_float(forecast.get("precip"), 0.0)
    if any(keyword in text for keyword in _RAIN_KEYWORDS):
        return True
    return precip > 0.0


class WeatherService:
    """天气服务（缓存 + 降级 + 施药建议）。"""

    def _resolve_location(self, location: str | None) -> str:
        """定位缺省值。"""
        return location or settings.weather_location

    async def _cache_get(self, key: str) -> Any | None:
        """读缓存；失败降级为 None。"""
        try:
            raw = await get_redis().get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 —— 缓存不可用不应影响业务
            logger.warning(f"天气缓存读取失败：{key}（{exc}）")
        return None

    async def _cache_set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """写缓存；``ttl`` 缺省用配置 TTL；失败静默。"""
        try:
            await get_redis().set(
                key,
                json.dumps(value, ensure_ascii=False),
                ex=ttl if ttl is not None else settings.weather_cache_ttl,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"天气缓存写入失败：{key}（{exc}）")

    async def _fetch(self, path: str, location: str) -> dict | None:
        """请求和风接口并返回 payload；任何失败返回 None（降级）。"""
        if not settings.weather_api_key:
            logger.warning("未配置 WEATHER_API_KEY，天气服务降级")
            return None

        url = f"{settings.weather_base_url.rstrip('/')}{path}"
        params = {"location": location, "key": settings.weather_api_key}
        try:
            async with make_client() as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
            if str(payload.get("code")) != "200":
                logger.warning(f"和风接口返回非 200：code={payload.get('code')}")
                return None
            return payload
        except Exception as exc:  # noqa: BLE001 —— 网络/解析失败一律降级
            logger.warning(f"和风接口调用失败：{exc}")
            return None

    async def get_now(self, location: str | None = None) -> NowWeather | None:
        """获取实时天气；降级返回 ``None``。"""
        loc = self._resolve_location(location)
        cache_key = f"weather:now:{loc}"

        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info(f"天气缓存命中：{cache_key}")
            return NowWeather(**cached)

        payload = await self._fetch("/v7/weather/now", loc)
        if not payload or "now" not in payload:
            return None

        now = payload["now"]
        result = NowWeather(
            location=loc,
            text=str(now.get("text", "")),
            temp=_to_float(now.get("temp")),
            humidity=_to_float(now.get("humidity")),
            wind_dir=str(now.get("windDir", "")),
            wind_scale=str(now.get("windScale", "")),
            updated_at=str(now.get("obsTime", "")),
            # —— 详情页扩展字段：和风原始字符串 → float；缺失/非法 → None ——
            feels_like=_opt_float(now.get("feelsLike")),
            precip=_opt_float(now.get("precip")),
            pressure=_opt_float(now.get("pressure")),
            vis=_opt_float(now.get("vis")),
            cloud=_opt_float(now.get("cloud")),
            dew=_opt_float(now.get("dew")),
            obs_time=str(now.get("obsTime", "")) or None,
        )
        await self._cache_set(cache_key, asdict(result))
        return result

    async def get_forecast(
        self,
        location: str | None = None,
        days: int = 3,
    ) -> list[DailyForecast]:
        """获取未来 N 天预报（1~7 天：≤3 走 3d 接口，>3 走 7d 接口截取）；降级返回 ``[]``。

        ⚠️ 缓存键必须带天数（``weather:forecast:<loc>:<days>``）：3 天与 7 天的
        原始 daily 长度不同，共用键会让 3 天缓存错喂 7 天请求。
        """
        loc = self._resolve_location(location)
        days = max(1, min(int(days), 7))
        path = "/v7/weather/3d" if days <= 3 else "/v7/weather/7d"
        cache_key = f"weather:forecast:{loc}:{days}"

        cached = await self._cache_get(cache_key)
        if cached is None:
            payload = await self._fetch(path, loc)
            if not payload or "daily" not in payload:
                return []
            # 原始 daily 列表整体入缓存（7d 最多 7 条），按 days 在解析阶段截取
            cached = payload["daily"]
            await self._cache_set(cache_key, cached)
        else:
            logger.info(f"天气缓存命中：{cache_key}")

        items: list[DailyForecast] = []
        for fc in cached[:days]:
            items.append(
                DailyForecast(
                    date=str(fc.get("fxDate", "")),
                    temp_max=_to_float(fc.get("tempMax")),
                    temp_min=_to_float(fc.get("tempMin")),
                    text_day=str(fc.get("textDay", "")),
                    text_night=str(fc.get("textNight", "")),
                    humidity=_to_float(fc["humidity"]) if fc.get("humidity") not in (None, "") else None,
                    precip=_to_float(fc["precip"]) if fc.get("precip") not in (None, "") else None,
                )
            )
        return items

    async def get_hourly(self, location: str | None = None) -> list[HourlyForecast]:
        """获取未来 24 小时逐时预报（和风 24h 接口）；降级返回 ``[]``。

        缓存键 ``weather:hourly:<loc>``，TTL 1800s（逐时数据更新快，短于日级缓存）。
        """
        loc = self._resolve_location(location)
        cache_key = f"weather:hourly:{loc}"

        cached = await self._cache_get(cache_key)
        if cached is None:
            payload = await self._fetch("/v7/weather/24h", loc)
            if not payload or "hourly" not in payload:
                return []
            cached = payload["hourly"]
            await self._cache_set(cache_key, cached, ttl=_HOURLY_CACHE_TTL)
        else:
            logger.info(f"天气缓存命中：{cache_key}")

        items: list[HourlyForecast] = []
        for h in cached[:24]:
            items.append(
                HourlyForecast(
                    fx_time=str(h.get("fxTime", "")),
                    temp=_to_float(h.get("temp")),
                    text=str(h.get("text", "")),
                    humidity=_opt_float(h.get("humidity")),
                    precip=_opt_float(h.get("precip")),
                    pop=_opt_float(h.get("pop")),
                    wind_dir=str(h.get("windDir", "")),
                    wind_scale=str(h.get("windScale", "")),
                )
            )
        return items

    async def get_spray_advice(self, location: str | None = None) -> SprayAdvice:
        """结合未来预报给出施药时机建议；无数据时降级。"""
        forecasts = await self.get_forecast(location, days=3)
        if not forecasts:
            return SprayAdvice(advice="暂无天气数据", next_rain_date=None, degraded=True)

        next_rain_date: str | None = None
        for fc in forecasts:
            if _is_rainy(fc):
                next_rain_date = fc.date
                break

        if next_rain_date:
            advice = (
                f"未来将出现降雨（{next_rain_date}），建议在降雨前抢晴施药，"
                "或在雨后叶面充分干燥时补施，避免药液被雨水冲刷失效。"
            )
        else:
            advice = (
                "未来 3 天无明显降雨，适宜施药；建议避开正午高温时段，"
                "选择清晨或傍晚喷施，并注意叶面均匀着药。"
            )
        return SprayAdvice(advice=advice, next_rain_date=next_rain_date, degraded=False)


# 模块级单例
weather_service = WeatherService()


__all__ = [
    "NowWeather",
    "DailyForecast",
    "HourlyForecast",
    "SprayAdvice",
    "WeatherService",
    "weather_service",
    "make_client",
]
