# -*- coding: utf-8 -*-
"""预警接口：H5 预警查询 + PC 规则 CRUD / 概览 / 刷新 / 记录。

设计依据：``docs/impl-pc-admin-v1.md`` §2.3 / §4。

数据隔离红线：``/warning/alerts*`` 仅返回「全局广播（``user_id`` 为 NULL）+ 定向本人」的记录；
越权访问统一 404 / 5001（防探测）。``/warning/rules|overview|refresh|records`` 仅管理员可用。

降级红线：``WEATHER_API_KEY`` 为空时，``/warning/overview`` 与 ``/warning/refresh`` 仍 200，
``degraded=true``，**绝不 500、绝不写库**。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_admin, get_current_user
from app.core.exceptions import (
    CODE_ALERT_NOT_FOUND,
    CODE_RULE_NOT_FOUND,
    BusinessError,
)
from app.core.response import ok, page_data
from app.core.security import decode_access_token
from app.models.user import User
from app.models.warning import AlertRecord, DiseaseWeatherRule
from app.schemas.warning import (
    AlertItem,
    RefreshIn,
    RiskEvaluation,
    RuleIn,
    RuleOut,
    RuleUpdate,
    UnreadCountOut,
    WarningForecastDayOut,
    WarningNowOut,
    WarningOverview,
    WarningRiskItem,
    WarningStats,
)
from app.services.monitor import make_event, monitor_hub
from app.services.weather import weather_service
from app.services.weather_risk import _alert_snapshot, weather_risk_engine
from app.utils.classmap import crop_cn_of, disease_cn_of

router = APIRouter()


# ============================================================
# 内部工具
# ============================================================
def _to_alert_item(record: AlertRecord, user_id: int, for_me: bool) -> AlertItem:
    """AlertRecord → AlertItem 出参。"""
    return AlertItem(
        id=record.id,
        source=record.source,
        disease=record.disease,
        disease_cn=disease_cn_of(record.disease),
        risk_level=record.risk_level,
        content=record.content,
        location=record.location,
        forecast_date=record.forecast_date.isoformat() if record.forecast_date else None,
        is_read=bool(record.is_read),
        for_me=for_me,
        created_at=record.created_at,
    )


def _to_rule_out(rule: DiseaseWeatherRule) -> RuleOut:
    """DiseaseWeatherRule → RuleOut 出参（附派生中文名）。"""
    return RuleOut(
        id=rule.id,
        disease=rule.disease,
        crop=rule.crop,
        temp_min=rule.temp_min,
        temp_max=rule.temp_max,
        humidity_min=rule.humidity_min,
        humidity_max=rule.humidity_max,
        rain_condition=rule.rain_condition,
        risk_level=rule.risk_level,
        advice=rule.advice,
        enabled=rule.enabled,
        disease_cn=disease_cn_of(rule.disease),
        crop_cn=crop_cn_of(rule.disease),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _visible_condition(user_id: int):
    """H5 可见性条件：全局广播或定向本人。"""
    return or_(AlertRecord.user_id.is_(None), AlertRecord.user_id == user_id)


# ============================================================
# H5 · 预警查询（普通用户）
# ============================================================
@router.get("/alerts", summary="我的预警列表（含全局广播）")
def list_alerts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 10,
    risk_level: Annotated[str | None, Query(description="按风险等级筛选 high/mid/low")] = None,
    unread_only: Annotated[bool, Query(description="仅未读")] = False,
) -> dict:
    """分页返回可见预警（全局 + 定向本人）。"""
    conditions = [_visible_condition(current_user.id)]
    if risk_level:
        conditions.append(AlertRecord.risk_level == risk_level)
    if unread_only:
        conditions.append(AlertRecord.is_read == 0)

    total = db.scalar(select(func.count()).select_from(AlertRecord).where(*conditions)) or 0
    rows = db.scalars(
        select(AlertRecord)
        .where(*conditions)
        .order_by(AlertRecord.created_at.desc(), AlertRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        _to_alert_item(r, current_user.id, for_me=True).model_dump() for r in rows
    ]
    return ok(page_data(items, int(total), page, page_size))


@router.get("/alerts/unread-count", summary="我的未读预警数")
def alerts_unread_count(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回可见预警中未读条数。"""
    count = db.scalar(
        select(func.count())
        .select_from(AlertRecord)
        .where(_visible_condition(current_user.id), AlertRecord.is_read == 0)
    ) or 0
    return ok(UnreadCountOut(count=int(count)).model_dump())


@router.post("/alerts/{alert_id}/read", summary="标记预警已读")
def mark_alert_read(
    alert_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """把可见预警置为已读；不存在或不可见 → 404 / 5001。"""
    record = db.scalar(
        select(AlertRecord).where(
            AlertRecord.id == alert_id,
            _visible_condition(current_user.id),
        )
    )
    if record is None:
        raise BusinessError(CODE_ALERT_NOT_FOUND, "预警记录不存在或无权访问", http_status=404)
    if not record.is_read:
        record.is_read = 1
        db.commit()
    return ok(None)


# ============================================================
# PC · 规则 CRUD（管理员）
# ============================================================
@router.get("/rules", summary="预警规则列表")
def list_rules(
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    enabled: Annotated[int | None, Query(ge=0, le=1, description="启用状态筛选")] = None,
    disease: Annotated[str | None, Query(max_length=100, description="按病害筛选")] = None,
) -> dict:
    """分页返回全部预警规则。"""
    conditions = []
    if enabled is not None:
        conditions.append(DiseaseWeatherRule.enabled == enabled)
    if disease:
        conditions.append(DiseaseWeatherRule.disease == disease)
    total = db.scalar(select(func.count()).select_from(DiseaseWeatherRule).where(*conditions)) or 0
    rows = db.scalars(
        select(DiseaseWeatherRule)
        .where(*conditions)
        .order_by(DiseaseWeatherRule.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_to_rule_out(r).model_dump() for r in rows]
    return ok(page_data(items, int(total), page, page_size))


@router.post("/rules", summary="新增预警规则")
def create_rule(
    payload: RuleIn,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """新增一条病害-气象规则。"""
    rule = DiseaseWeatherRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return ok(_to_rule_out(rule))


@router.put("/rules/{rule_id}", summary="更新预警规则（可部分）")
def update_rule(
    rule_id: int,
    payload: RuleUpdate,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """局部更新预警规则；不存在 → 404 / 5002。"""
    rule = db.get(DiseaseWeatherRule, rule_id)
    if rule is None:
        raise BusinessError(CODE_RULE_NOT_FOUND, "预警规则不存在", http_status=404)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return ok(_to_rule_out(rule))


@router.delete("/rules/{rule_id}", summary="删除预警规则")
def delete_rule(
    rule_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """删除预警规则；不存在 → 404 / 5002。"""
    rule = db.get(DiseaseWeatherRule, rule_id)
    if rule is None:
        raise BusinessError(CODE_RULE_NOT_FOUND, "预警规则不存在", http_status=404)
    db.delete(rule)
    db.commit()
    return ok(None)


# ============================================================
# PC · 概览 / 刷新 / 记录（管理员）
# ============================================================
@router.get("/overview", summary="预警总览")
async def warning_overview(
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    location: Annotated[str | None, Query(max_length=50, description="位置，缺省用配置")] = None,
) -> dict:
    """返回天气 + 当前风险总览（不写库）。天气不可用时 ``degraded=true``。"""
    evaluation = await weather_risk_engine.evaluate(location, persist=False, db=db)

    now = None
    forecast: list[WarningForecastDayOut] = []
    try:
        now_data = await weather_service.get_now(location)
        if now_data is not None:
            now = WarningNowOut(
                location=now_data.location,
                text=now_data.text,
                temp=now_data.temp,
                humidity=now_data.humidity,
                wind_dir=now_data.wind_dir,
                wind_scale=now_data.wind_scale,
                updated_at=now_data.updated_at,
            )
        days = int(getattr(settings, "warning_forecast_days", 3) or 3)
        for item in await weather_service.get_forecast(location, days=days):
            forecast.append(
                WarningForecastDayOut(
                    date=item.date,
                    temp_max=item.temp_max,
                    temp_min=item.temp_min,
                    text_day=item.text_day,
                    text_night=item.text_night,
                    humidity=item.humidity,
                    precip=item.precip,
                )
            )
    except Exception as exc:  # noqa: BLE001 —— 天气取用失败一律降级，绝不 500
        logger.warning(f"预警总览获取天气失败（已降级）：{type(exc).__name__}: {exc}")

    stats = WarningStats()
    current_risks: list[WarningRiskItem] = []
    for hit in evaluation.hits:
        if hit.risk_level == "high":
            stats.high += 1
        elif hit.risk_level == "mid":
            stats.mid += 1
        elif hit.risk_level == "low":
            stats.low += 1
        current_risks.append(
            WarningRiskItem(
                disease=hit.disease,
                disease_cn=hit.disease_cn,
                risk_level=hit.risk_level,
                forecast_date=hit.forecast_date,
                advice=hit.advice,
            )
        )

    last_refresh = db.scalar(
        select(func.max(AlertRecord.created_at)).where(AlertRecord.source == "weather")
    )
    overview = WarningOverview(
        degraded=evaluation.degraded,
        location=evaluation.location,
        now=now,
        forecast=forecast,
        current_risks=current_risks,
        stats=stats,
        last_refresh_at=_iso(last_refresh),
    )
    return ok(overview)


@router.post("/refresh", summary="手动触发风险评估")
async def refresh_warning(
    payload: RefreshIn | None,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """立即评估一次（天气不可用时 200 + ``degraded=true``，零写入）。"""
    location = payload.location if payload else None
    evaluation = await weather_risk_engine.evaluate(location, persist=True, db=db)
    out = RiskEvaluation(
        degraded=evaluation.degraded,
        location=evaluation.location,
        evaluated_rules=evaluation.evaluated_rules,
        matched=evaluation.matched,
        created=evaluation.created,
        alerts=[AlertItem(**a) for a in evaluation.alerts],
    )
    return ok(out)


@router.get("/records", summary="预警记录列表（全量）")
def list_records(
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    risk_level: Annotated[str | None, Query(description="按风险等级筛选")] = None,
    source: Annotated[str | None, Query(description="按来源筛选 weather/detection")] = None,
    location: Annotated[str | None, Query(max_length=50)] = None,
    start: Annotated[datetime | None, Query(description="起始时间（UTC）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（UTC）")] = None,
) -> dict:
    """管理员分页查看全量预警记录。"""
    conditions = []
    if risk_level:
        conditions.append(AlertRecord.risk_level == risk_level)
    if source:
        conditions.append(AlertRecord.source == source)
    if location:
        conditions.append(AlertRecord.location == location)
    if start is not None:
        conditions.append(AlertRecord.created_at >= start)
    if end is not None:
        conditions.append(AlertRecord.created_at <= end)
    total = db.scalar(select(func.count()).select_from(AlertRecord).where(*conditions)) or 0
    rows = db.scalars(
        select(AlertRecord)
        .where(*conditions)
        .order_by(AlertRecord.created_at.desc(), AlertRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_to_alert_item(r, admin.id, for_me=False).model_dump() for r in rows]
    return ok(page_data(items, int(total), page, page_size))


# ============================================================
# 工具（模块内）
# ============================================================
def _iso(value: datetime | None) -> str | None:
    """datetime → ISO-8601 带 Z；``None`` 原样返回。"""
    if value is None:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# H5 · 预警实时推送（``WS /warning/ws/alerts``）
# ============================================================
# 关闭码语义（accept-first：先握手再 close，浏览器才拿得到自定义 code）
CLOSE_UNAUTHORIZED = 4401  # 无 token / token 无效
CLOSE_FORBIDDEN = 4403  # 用户不存在或被禁用
CLOSE_TOO_MANY = 4429  # 连接数超限（复用 MONITOR_MAX_CONNECTIONS）

# 首帧 hello 携带的近期预警条数
_ALERT_HELLO_LIMIT = 10


def _resolve_ws_user(db: Session, token: str | None) -> tuple[str, User | None]:
    """解析 query token → 校验 JWT → 查 users → 校验 ``status == 1``。

    返回三态，便于区分 4401 / 4403：

    - ``("unauthorized", None)``：无 token / token 签名或格式非法 → close 4401；
    - ``("forbidden", None)``：token 合法但**用户不存在或被禁用** → close 4403；
    - ``("ok", user)``：鉴权通过。

    任一环节失败均不抛异常（握手方据此按 close code 关闭）。
    """
    if not token:
        return ("unauthorized", None)
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except Exception:  # noqa: BLE001 —— token 无效一律按未授权处理
        return ("unauthorized", None)
    user = db.get(User, user_id)
    if user is None or user.status != 1:
        return ("forbidden", None)
    return ("ok", user)


def _alert_ws_item(record: AlertRecord) -> dict[str, Any]:
    """AlertRecord → WS 事件载荷 dict（``created_at`` 序列化为 ISO-8601 带 Z）。

    字段与 REST ``GET /warning/alerts`` 的 ``AlertItem`` 对齐（并冗余一份 ``alert_id``），
    便于 H5 直接插入列表顶部。
    """
    return {
        "id": record.id,
        "alert_id": record.id,
        "source": record.source,
        "disease": record.disease,
        "disease_cn": disease_cn_of(record.disease),
        "risk_level": record.risk_level,
        "content": record.content,
        "location": record.location,
        "forecast_date": record.forecast_date.isoformat() if record.forecast_date else None,
        "is_read": bool(record.is_read),
        "for_me": True,
        "created_at": _iso(record.created_at),
    }


def _recent_visible_items(db: Session, user_id: int, limit: int) -> list[dict[str, Any]]:
    """该用户可见的近期预警（全局广播 + 定向本人），按时间倒序（首帧 hello 用）。"""
    rows = db.scalars(
        select(AlertRecord)
        .where(_visible_condition(user_id))
        .order_by(AlertRecord.created_at.desc(), AlertRecord.id.desc())
        .limit(limit)
    ).all()
    return [_alert_ws_item(r) for r in rows]


def _lookup_alert(alert_id: int) -> tuple[int | None, dict[str, Any]] | None:
    """用事件载荷里的 ``alert_id`` **回查一次库**，取真实归属 + 出参快照。

    关键设计：``warning.created`` 事件载荷**不含 user_id**，而可见性由
    ``alert_records.user_id`` 决定（``None`` = 全局广播；非空 = 定向本人）。
    事件量极低（天气预警 6 小时一轮），一次主键查询可忽略；且天然兼容将来
    检测类定向预警。

    Returns:
        ``(owner_user_id, ws_item)``；记录不存在 / 查询异常时返回 ``None``
        （调用方据此**丢弃**，宁可漏推也绝不串号）。
    """
    session = SessionLocal()
    try:
        record = session.get(AlertRecord, alert_id)
        if record is None:
            return None
        return record.user_id, _alert_ws_item(record)
    except Exception as exc:  # noqa: BLE001 —— 回查失败按不可判定处理
        logger.warning(f"预警事件回查失败（已忽略）：{type(exc).__name__}: {exc}")
        return None
    finally:
        session.close()


class AlertHub:
    """预警事件扇出中心：按「可见性」把 ``warning.created`` 定向推给 H5 用户连接。

    可见性语义与 REST ``GET /warning/alerts`` 完全一致（``_visible_condition``）：

    - ``user_id is None`` → 全局广播 → 推给**所有**在线连接；
    - ``user_id == X``    → 只推给 **X 的**连接。

    与 admin 的 ``monitor_hub`` 不同：用户 WS **不进入** monitor_hub 的全体扇出池，
    而是作为 monitor_hub 的**额外监听器**接收事件后自行过滤，**绝无串号**。
    """

    def __init__(self) -> None:
        self._all: set[WebSocket] = set()
        self._by_user: dict[int, set[WebSocket]] = {}
        self._locks: dict[WebSocket, asyncio.Lock] = {}

    @property
    def connection_count(self) -> int:
        """当前本地用户 WS 连接数。"""
        return len(self._all)

    def register(self, ws: WebSocket, user_id: int) -> None:
        """把一条已通过握手的用户 WS 登记到「全体池」+「该用户池」。"""
        uid = int(user_id)
        self._all.add(ws)
        self._by_user.setdefault(uid, set()).add(ws)
        self._locks[ws] = asyncio.Lock()

    def unregister(self, ws: WebSocket) -> None:
        """从全体池与所属用户池摘除；清空空集合避免字典膨胀。"""
        self._all.discard(ws)
        for uid in list(self._by_user.keys()):
            conns = self._by_user[uid]
            conns.discard(ws)
            if not conns:
                self._by_user.pop(uid, None)
        self._locks.pop(ws, None)

    async def send_to(
        self,
        ws: WebSocket,
        payload: dict,
        *,
        text: str | None = None,
    ) -> None:
        """向单条连接发送文本帧（每连接加锁，避免心跳与广播并发写坏帧）。"""
        frame = text if text is not None else json.dumps(payload, ensure_ascii=False)
        lock = self._locks.get(ws)
        if lock is None:
            await ws.send_text(frame)
        else:
            async with lock:
                await ws.send_text(frame)

    def _targets_for(self, owner_id: int | None) -> set[WebSocket]:
        """按归属返回本次应推送的连接集合（全局 → 全体；定向 → 仅该用户）。"""
        if owner_id is None:
            return set(self._all)
        return set(self._by_user.get(int(owner_id), set()))

    async def handle_event(self, payload: dict) -> None:
        """monitor_hub 监听器：仅处理 ``warning.created``，按可见性定向扇出。

        **串号红线**：按真实 ``alert_records.user_id`` 过滤——全局推全体、定向仅本人；
        回查不到记录时**丢弃**（宁可漏推也不串号）。
        """
        if payload.get("type") != "warning.created":
            return
        if not self._all:
            # 无在线连接：无人可推，跳过回查（也避免无谓的 DB 访问）
            return
        data = payload.get("data") or {}
        try:
            alert_id = int(data.get("alert_id"))
        except (TypeError, ValueError):
            logger.warning("warning.created 事件缺少 alert_id，无法判定可见性，已丢弃")
            return

        looked_up = _lookup_alert(alert_id)
        if looked_up is None:
            logger.warning(f"warning.created 回查不到预警记录 id={alert_id}，已丢弃（不串号）")
            return
        owner_id, ws_item = looked_up

        event = make_event("warning.created", ws_item)
        text = json.dumps(event, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self._targets_for(owner_id):
            try:
                await self.send_to(ws, event, text=text)
            except Exception:  # noqa: BLE001 —— 单连接失败不影响其它连接
                dead.append(ws)
        for ws in dead:
            self.unregister(ws)


# 模块级单例 + 挂到 monitor 事件总线上（导入期完成；监听器异常已被总线吞掉）
alert_hub = AlertHub()
monitor_hub.add_listener(alert_hub.handle_event)


async def _alert_heartbeat_loop(websocket: WebSocket) -> None:
    """服务端定时发 ``ping``（复用 ``MONITOR_HEARTBEAT_SECONDS``）；断开时静默退出。"""
    interval = max(5, int(settings.monitor_heartbeat_seconds))
    try:
        while True:
            await asyncio.sleep(interval)
            await alert_hub.send_to(websocket, make_event("ping", {}))
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001 —— 连接已断，主循环会清理
        return


async def _handle_client_frame(websocket: WebSocket, raw: str) -> None:
    """处理客户端帧：``pong`` 忽略；``ping`` 回 ``pong``；未知帧记 debug 后忽略。"""
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        logger.debug("预警 WS 收到非 JSON 帧，已忽略")
        return
    if not isinstance(frame, dict):
        return
    kind = frame.get("type")
    if kind == "ping":
        await alert_hub.send_to(websocket, make_event("pong", {}))
    elif kind == "pong":
        return
    else:
        logger.debug(f"预警 WS 未知帧已忽略：{kind}")


@router.websocket("/ws/alerts", name="warning-alerts")
async def ws_alerts(
    websocket: WebSocket,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """H5 用户预警实时流：**先 accept** → 鉴权 → 失败按 close code 关闭。

    任何已登录用户可用（非 admin-only）。协议与 admin ``/admin/ws/monitor`` 同源：
    ``{v,type,ts,data}`` 信封，支持 ``hello``（首帧，带该用户可见的近期预警快照）、
    ``warning.created``、``ping``/``pong``。

    网络层要点（本项目已踩过的坑）：Starlette 在 ``accept()`` 之前的 ``close()``
    会被翻译成 HTTP 403 握手拒绝，浏览器拿不到自定义 close code；故必须先完成
    101 握手，再 close 才能把 4401/4403/4429 送达客户端。
    """
    await websocket.accept()

    status, user = _resolve_ws_user(db, websocket.query_params.get("token"))
    if status == "unauthorized":
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    if status == "forbidden" or user is None:
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    if alert_hub.connection_count >= int(settings.monitor_max_connections):
        await websocket.close(code=CLOSE_TOO_MANY)
        return

    alert_hub.register(websocket, user.id)
    heartbeat_task = asyncio.create_task(_alert_heartbeat_loop(websocket), name="alert-heartbeat")
    try:
        hello = make_event(
            "hello",
            {
                "server": "cropdoctor",
                "channel": "warning",
                "heartbeat_seconds": int(settings.monitor_heartbeat_seconds),
                "recent": _recent_visible_items(db, user.id, _ALERT_HELLO_LIMIT),
            },
        )
        await alert_hub.send_to(websocket, hello)
        while True:
            raw = await websocket.receive_text()
            await _handle_client_frame(websocket, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 —— 连接异常按断开处理
        logger.debug(f"预警 WS 异常关闭：{type(exc).__name__}: {exc}")
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(BaseException):
            await heartbeat_task
        alert_hub.unregister(websocket)


__all__ = [
    "router",
    "AlertHub",
    "alert_hub",
    "CLOSE_UNAUTHORIZED",
    "CLOSE_FORBIDDEN",
    "CLOSE_TOO_MANY",
]
