# -*- coding: utf-8 -*-
"""病害气象风险引擎：``disease_weather_rules`` × 天气预报 → ``alert_records``。

设计依据：``docs/impl-pc-admin-v1.md`` §4。

降级红线（§4.2）：``WEATHER_API_KEY`` 为空 / 天气接口失败时 ``weather_service.get_forecast()``
返回 ``[]`` → 引擎**立即返回** ``degraded=True``，**零写库、零发事件**，绝不 500。

多条件叠加提权（方案 B）：命中一条规则后，按该规则**声明**的维度数（温度 / 湿度 / 降雨 /
作物，最多 4 维）重新定级——**四维齐全才保留规则原级别**，声明不全则**降一级**
（``high→mid``、``mid→low``、``low→低于 low 且不生成该预警``）。可由配置键
``WARNING_REQUIRE_FULL_DIMENSIONS=false`` 完全回退到旧行为（命中即按原级别）。
"""
from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.warning import AlertRecord, DiseaseWeatherRule
from app.services.weather import DailyForecast, _is_rainy, weather_service
from app.utils.classmap import crop_cn_of, disease_cn_of

# 风险等级 → 中文
RISK_CN: dict[str, str] = {"high": "高", "mid": "中", "low": "低"}
_CONTENT_MAX = 500

# 维度定义（顺序即文案展示顺序）：温度 / 湿度 / 降雨 / 作物
_DIM_ORDER: tuple[str, ...] = ("temp", "humidity", "rain", "crop")
_DIM_CN: dict[str, str] = {"temp": "温度", "humidity": "湿度", "rain": "降雨", "crop": "作物"}
# 风险等级强度升序（索引即强度，便于「降一级」）
_LEVEL_ORDER: tuple[str, ...] = ("low", "mid", "high")
# 中文数词（用于「两维/三维」文案）
_CN_NUM: dict[int, str] = {0: "零", 1: "一", 2: "两", 3: "三", 4: "四"}


def _cfg(name: str, default: Any) -> Any:
    """读取配置键；键缺失时回退默认值（配置键由 T01 落 ``config.py``）。"""
    return getattr(settings, name, default)


def _declared_dimensions(rule: DiseaseWeatherRule) -> dict[str, bool]:
    """规则**声明**了哪些维度（纯声明判定，与当日数据无关）。

    某维度只要声明了任一约束即计 1：温度见 ``temp_min/temp_max``，湿度见
    ``humidity_min/humidity_max``，降雨见 ``rain_condition != 'any'``，作物见 ``crop`` 非空。
    最多 4 维。

    Args:
        rule: 病害-气象规则。

    Returns:
        ``{维度名: 是否声明}``，键固定为 ``_DIM_ORDER`` 四项。
    """
    return {
        "temp": rule.temp_min is not None or rule.temp_max is not None,
        "humidity": rule.humidity_min is not None or rule.humidity_max is not None,
        "rain": (rule.rain_condition or "any") != "any",
        "crop": bool(rule.crop and str(rule.crop).strip()),
    }


def _downgrade_level(level: str) -> str | None:
    """风险等级降一级。

    Args:
        level: 原级别（``high`` / ``mid`` / ``low``）。

    Returns:
        降级后的级别；``low`` 再降返回 ``None``（表示低于 low，不生成该预警）。
        未知级别（枚举约束下不应发生）原样返回，不做降级。
    """
    if level not in _LEVEL_ORDER:
        return level
    idx = _LEVEL_ORDER.index(level)
    if idx <= 0:
        return None
    return _LEVEL_ORDER[idx - 1]


def _grade_level(rule: DiseaseWeatherRule) -> tuple[str | None, dict[str, bool]]:
    """按「声明维度数」对命中规则重新定级（多条件叠加提权）。

    规则（``WARNING_REQUIRE_FULL_DIMENSIONS=true`` 时生效）：
    声明的维度数为 4（温度·湿度·降雨·作物齐全）→ 保留规则原级别；
    否则降一级（``low`` 再降 → ``None``，不生成）。

    Args:
        rule: 命中的病害-气象规则。

    Returns:
        ``(最终等级或 None, 声明维度字典)``；``None`` 表示低于 low、不生成。若
        ``WARNING_REQUIRE_FULL_DIMENSIONS=false`` 则直接返回原级别（完全回退旧行为）。
    """
    dims = _declared_dimensions(rule)
    if not bool(_cfg("warning_require_full_dimensions", True)):
        return rule.risk_level, dims  # 关闭提权 → 完全回退旧行为
    declared = sum(1 for dim in _DIM_ORDER if dims[dim])
    if declared >= len(_DIM_ORDER):
        return rule.risk_level, dims  # 四维齐全 → 保留原级别
    return _downgrade_level(rule.risk_level), dims


def _grade_note(dims: dict[str, bool], level: str, base_level: str) -> str:
    """生成预警文案中的「判定依据」尾注（透明性）。

    形如 ``（依据：温度·湿度·降雨·作物 四维条件同时满足）`` 或
    ``（依据：湿度·降雨 两维条件；未声明温度·作物，风险由中降为低）``。

    Args:
        dims: 声明维度字典。
        level: 最终等级。
        base_level: 规则原级别。

    Returns:
        括号包裹的判定依据文本。
    """
    declared_dims = [dim for dim in _DIM_ORDER if dims.get(dim)]
    missing_dims = [dim for dim in _DIM_ORDER if not dims.get(dim)]
    declared_cn = "·".join(_DIM_CN[dim] for dim in declared_dims) or "无"
    count = len(declared_dims)
    if not missing_dims:
        return f"（依据：{declared_cn} 四维条件同时满足）"
    missing_cn = "·".join(_DIM_CN[dim] for dim in missing_dims)
    if level == base_level:
        # 未发生降级（如开关关闭）→ 只陈述依据，不写「降级」字样
        return f"（依据：{declared_cn} {_CN_NUM.get(count, str(count))}维条件；未声明{missing_cn}）"
    base_cn = RISK_CN.get(base_level, base_level)
    level_cn = RISK_CN.get(level, level)
    return (
        f"（依据：{declared_cn} {_CN_NUM.get(count, str(count))}维条件；"
        f"未声明{missing_cn}，风险由{base_cn}降为{level_cn}）"
    )


@dataclass
class RiskHit:
    """单条「规则 × 单日」命中。"""

    rule_id: int
    disease: str
    disease_cn: str | None
    crop: str | None
    risk_level: str
    advice: str | None
    forecast_date: str  # YYYY-MM-DD
    matched: dict
    # 便于落库时直接取日期对象，避免二次解析
    forecast_day: date | None = None
    content: str = ""


@dataclass
class RiskEvaluation:
    """一次风险评估的结果。"""

    degraded: bool
    location: str | None = None
    evaluated_rules: int = 0
    matched: int = 0
    created: int = 0
    hits: list[RiskHit] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)


class WeatherRiskEngine:
    """天气风险引擎（规则匹配 + 去重写库 + 事件发布）。"""

    def _build_content(
        self,
        rule: DiseaseWeatherRule,
        disease_cn: str | None,
        crop_cn: str | None,
        forecast_date: str,
        risk_level: str,
        dims: dict[str, bool],
    ) -> str:
        """按设计 §4.1 拼接预警文案（截断至 500 字以内适配列宽）。

        Args:
            rule: 命中的规则。
            disease_cn: 病害中文名。
            crop_cn: 作物中文名。
            forecast_date: 预报日期（YYYY-MM-DD）。
            risk_level: **最终定级**（经多条件提权降级后），须与落库级别一致。
            dims: 声明维度字典，用于生成「判定依据」尾注。

        Returns:
            截断至 ``_CONTENT_MAX`` 字以内的预警文案。
        """
        name = f"{crop_cn or ''}{disease_cn or rule.disease}"
        risk_cn = RISK_CN.get(risk_level, risk_level)
        advice = rule.advice or ""
        # 仅当多条件叠加提权生效时才附加「判定依据」尾注；关闭开关时完全回退旧文案
        note = ""
        if bool(_cfg("warning_require_full_dimensions", True)):
            note = _grade_note(dims, risk_level, rule.risk_level)
        text = f"{name} 在未来 {forecast_date} 有{risk_cn}爆发风险。{advice}{note}"
        return text[:_CONTENT_MAX]

    def match_rule(self, rule: DiseaseWeatherRule, day: DailyForecast) -> RiskHit | None:
        """单规则 × 单日 的匹配判定 + 定级（纯函数，便于单测）。

        匹配规则见设计 §4.1：温度区间求交；湿度缺数据时忽略该约束（不判否）；
        降雨按 ``rain_condition``；仅启用规则参与（由调用方保证）。

        命中后按「声明维度数」定级（``_grade_level``）：四维齐全保留原级别，否则降一级；
        降级后低于 ``low`` 则返回 ``None``（不生成该预警）。

        Args:
            rule: 病害-气象规则。
            day: 单日预报。

        Returns:
            命中且未降至 low 以下的 ``RiskHit``；否则 ``None``。
        """
        # 温度区间求交
        if rule.temp_min is not None and day.temp_max < rule.temp_min:
            return None
        if rule.temp_max is not None and day.temp_min > rule.temp_max:
            return None

        # 湿度：有约束但当日湿度缺失 → 忽略该约束（避免因缺数据漏报）
        if rule.humidity_min is not None or rule.humidity_max is not None:
            if day.humidity is not None:
                if rule.humidity_min is not None and day.humidity < rule.humidity_min:
                    return None
                if rule.humidity_max is not None and day.humidity > rule.humidity_max:
                    return None

        # 降雨
        rain_condition = rule.rain_condition or "any"
        rainy = _is_rainy(day)
        if rain_condition == "rain" and not rainy:
            return None
        if rain_condition == "no_rain" and rainy:
            return None

        # 多条件叠加提权定级（dims = 该规则声明的维度）
        level, dims = _grade_level(rule)
        if level is None:
            # 声明不全且原级别为 low → 降级低于 low，不生成该预警
            return None

        forecast_date = day.date or ""
        forecast_day = _safe_date(forecast_date)
        disease_cn = disease_cn_of(rule.disease)
        crop_cn = crop_cn_of(rule.disease) or None
        return RiskHit(
            rule_id=rule.id,
            disease=rule.disease,
            disease_cn=disease_cn,
            crop=rule.crop,
            risk_level=level,
            advice=rule.advice,
            forecast_date=forecast_date,
            matched={
                # 沿用旧语义：规则声明了哪些维度（dim 声明 + 当日数据可得）
                "temp": dims["temp"],
                "humidity": dims["humidity"] and day.humidity is not None,
                "rain": dims["rain"],
                "crop": dims["crop"],
            },
            forecast_day=forecast_day,
            content=self._build_content(rule, disease_cn, crop_cn, forecast_date, level, dims),
        )

    def _exists(self, db: Session, hit: RiskHit, location: str | None) -> bool:
        """去重：按 ``(disease, forecast_date, location, risk_level, source)`` 判是否已存在。"""
        if hit.forecast_day is None:
            return True  # 日期非法视作不可写，跳过
        count = db.scalar(
            select(func.count())
            .select_from(AlertRecord)
            .where(
                AlertRecord.disease == hit.disease,
                AlertRecord.forecast_date == hit.forecast_day,
                AlertRecord.location.is_(None) if location is None else AlertRecord.location == location,
                AlertRecord.risk_level == hit.risk_level,
                AlertRecord.source == "weather",
            )
        )
        return bool(count)

    async def evaluate(
        self,
        location: str | None = None,
        *,
        persist: bool = True,
        db: Session | None = None,
    ) -> RiskEvaluation:
        """读预报 → 读启用规则 → 逐日逐规则匹配 → 去重后写库 → 发事件。

        预报不可用（降级）→ 直接返回 ``degraded=True``，**零写入、零事件**。
        """
        loc = location or getattr(settings, "weather_location", None) or None
        own_session = db is None
        if db is None:
            db = SessionLocal()
        try:
            rules = list(
                db.scalars(
                    select(DiseaseWeatherRule).where(DiseaseWeatherRule.enabled == 1)
                ).all()
            )
            if not rules:
                logger.info("无启用预警规则，风险引擎跳过评估")
                return RiskEvaluation(degraded=False, location=loc, evaluated_rules=0)

            days = int(_cfg("warning_forecast_days", 3) or 3)
            try:
                forecasts = await weather_service.get_forecast(loc, days=days)
            except Exception as exc:  # noqa: BLE001 —— 天气不可用一律降级
                logger.warning(f"获取天气预报失败，风险引擎降级：{type(exc).__name__}: {exc}")
                forecasts = []

            if not forecasts:
                logger.warning("天气预报不可用，风险引擎降级（零写入、零事件）")
                return RiskEvaluation(
                    degraded=True,
                    location=loc,
                    evaluated_rules=len(rules),
                )

            hits: list[RiskHit] = []
            for rule in rules:
                for day in forecasts:
                    hit = self.match_rule(rule, day)
                    if hit is not None:
                        hits.append(hit)

            if not persist:
                return RiskEvaluation(
                    degraded=False,
                    location=loc,
                    evaluated_rules=len(rules),
                    matched=len(hits),
                    created=0,
                    hits=hits,
                )

            created: list[AlertRecord] = []
            for hit in hits:
                if self._exists(db, hit, loc):
                    continue
                record = AlertRecord(
                    source="weather",
                    disease=hit.disease,
                    risk_level=hit.risk_level,
                    content=hit.content,
                    user_id=None,
                    location=loc,
                    forecast_date=hit.forecast_day,
                    is_read=0,
                )
                db.add(record)
                created.append(record)

            if created:
                db.commit()
                for record in created:
                    db.refresh(record)

            alerts = [_alert_snapshot(record, for_me=True) for record in created]
            await _publish_created(alerts)

            logger.info(
                f"风险引擎评估完成：规则 {len(rules)} 条，命中 {len(hits)}，新建预警 {len(created)}"
            )
            return RiskEvaluation(
                degraded=False,
                location=loc,
                evaluated_rules=len(rules),
                matched=len(hits),
                created=len(created),
                hits=hits,
                alerts=alerts,
            )
        finally:
            if own_session and db is not None:
                db.close()


def _safe_date(text: str | None) -> date | None:
    """把 ``YYYY-MM-DD`` 字符串解析为 ``date``；失败返回 ``None``。"""
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _alert_snapshot(record: AlertRecord, *, for_me: bool) -> dict:
    """AlertRecord → 出参 dict（供 ``POST /warning/refresh`` 返回快照）。"""
    return {
        "id": record.id,
        "source": record.source,
        "disease": record.disease,
        "disease_cn": disease_cn_of(record.disease),
        "risk_level": record.risk_level,
        "content": record.content,
        "location": record.location,
        "forecast_date": record.forecast_date.isoformat() if record.forecast_date else None,
        "is_read": bool(record.is_read),
        "for_me": for_me,
        "created_at": record.created_at,
    }


async def _publish_created(alerts: list[dict]) -> None:
    """发布 ``warning.created`` 事件（monitor 未落地 / 异常一律静默降级）。"""
    if not alerts:
        return
    try:
        from app.services.monitor import publish_event  # noqa: PLC0415 —— 惰性导入，避免耦合
    except Exception as exc:  # noqa: BLE001 —— monitor 未落地时静默
        logger.debug(f"monitor 服务不可用，跳过预警事件发布：{exc}")
        return
    for alert in alerts:
        try:
            await publish_event(
                "warning.created",
                {
                    "alert_id": alert["id"],
                    "source": alert["source"],
                    "disease": alert["disease"],
                    "disease_cn": alert["disease_cn"],
                    "risk_level": alert["risk_level"],
                    "location": alert["location"],
                    "forecast_date": alert["forecast_date"],
                    "content": alert["content"],
                    "created_at": _iso(alert["created_at"]),
                },
            )
        except Exception as exc:  # noqa: BLE001 —— 事件发布失败绝不影响主链路
            logger.warning(f"发布预警事件失败（已忽略）：{type(exc).__name__}: {exc}")


def _iso(value: Any) -> str:
    """datetime → ISO-8601 带 Z。"""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


# ============================================================
# 定时刷新（无 Celery）：供 ``main.py::lifespan`` 调用
# ============================================================
_scheduler_thread: threading.Thread | None = None


def start_scheduler() -> threading.Thread | None:
    """启动预警定时刷新守护线程（幂等）。

    设计 §4.3：``WARNING_ENABLED=true`` 时启动后台任务，**首轮延迟 60s**（错峰），
    之后每 ``WARNING_REFRESH_INTERVAL_MINUTES`` 分钟评估一次；任务体整体吞异常，
    **绝不影响启动与主链路**。

    Returns:
        启动的线程对象；若已禁用或已在运行则返回已有线程 / ``None``。
    """
    global _scheduler_thread
    if not bool(_cfg("warning_enabled", True)):
        logger.info("预警定时刷新已禁用（WARNING_ENABLED=false）")
        return None
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return _scheduler_thread
    _scheduler_thread = threading.Thread(
        target=_scheduler_entry, name="warning-refresh", daemon=True
    )
    _scheduler_thread.start()
    logger.info("预警定时刷新已启动（首轮延迟 60s）")
    return _scheduler_thread


def _scheduler_entry() -> None:
    """守护线程入口：独立事件循环跑定时评估，任何退出异常均吞掉。"""
    try:
        asyncio.run(_scheduler_loop())
    except Exception as exc:  # noqa: BLE001 —— 绝不冒泡
        logger.warning(f"预警定时刷新线程退出：{type(exc).__name__}: {exc}")


async def _scheduler_loop() -> None:
    """定时评估循环。"""
    interval = max(1, int(_cfg("warning_refresh_interval_minutes", 360) or 360))
    with contextlib.suppress(Exception):
        await asyncio.sleep(60)  # 首轮延迟，错峰启动
    while True:
        try:
            result = await weather_risk_engine.evaluate()
            logger.info(
                f"预警定时刷新完成：degraded={result.degraded} "
                f"matched={result.matched} created={result.created}"
            )
        except Exception as exc:  # noqa: BLE001 —— 单轮失败不影响后续
            logger.warning(f"预警定时刷新失败（已忽略）：{type(exc).__name__}: {exc}")
        await asyncio.sleep(interval * 60)


# 模块级单例
weather_risk_engine = WeatherRiskEngine()


__all__ = [
    "RISK_CN",
    "RiskHit",
    "RiskEvaluation",
    "WeatherRiskEngine",
    "weather_risk_engine",
    "start_scheduler",
    "_alert_snapshot",
]
