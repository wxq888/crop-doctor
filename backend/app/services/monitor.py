# -*- coding: utf-8 -*-
"""monitor 事件总线：Redis Pub/Sub + 本地扇出 + 环形快照。

设计依据：``docs/impl-pc-admin-v1.md`` §3.1 / §3.3。

数据流::

    检测完成 / 反馈 / 预警  ──►  MonitorHub.publish_event(type, data)
                                     │
                                     ├─► Redis PUBLISH  channel（跨进程）
                                     ├─► LPUSH + LTRIM 快照键（断线补拉，TTL 24h）
                                     └─► 本地即时扇出（单进程零延迟，去重防回灌重复）

    [每进程] subscribe_loop() ──► broadcast_local() ──► 所有 admin WS

**降级不抛错**：Redis 不可用时 ``publish_event`` 自动兜底为本地扇出（单实例仍可用），
``recent`` 返回空列表；绝不因 Redis 故障拖垮 WS 或主链路。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis_client import get_redis
from app.models.detection import DetectionRecord
from app.models.user import User
from app.schemas.common import to_utc_z
from app.services import severity
from app.services.classmap import crop_cn_of, derive_crop, disease_cn_of
from app.utils import storage

# 本地广播去重窗口：丢弃订阅回路回灌的「相同帧」，避免 publish + 本地扇出双发
_DEDUP_WINDOW = 500
# 快照键 TTL（秒）：24h
_SNAPSHOT_TTL_SECONDS = 86400


def _now_iso() -> str:
    """当前 UTC 时间（ISO-8601 带 Z）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """构造 ``{v,type,ts,data}`` 事件信封（``ts`` 为 ISO-8601 带 Z）。"""
    return {"v": 1, "type": event_type, "ts": _now_iso(), "data": data or {}}


class MonitorHub:
    """进程内连接池 + 事件扇出；跨进程经 Redis Pub/Sub。"""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._locks: dict[WebSocket, asyncio.Lock] = {}
        self._pubsub: Any | None = None
        self._sub_task: asyncio.Task[None] | None = None
        self._started = False
        # 近期已广播的「帧文本」，用于丢弃订阅回路回灌的重复帧
        self._sent_texts: deque[str] = deque(maxlen=_DEDUP_WINDOW)
        # 额外事件监听器（如预警定向扇出）：在 WS 扇出之后、按**去重后的唯一帧**调用一次
        self._listeners: list[Any] = []

    # ---- 连接池管理 ----
    @property
    def connection_count(self) -> int:
        """当前本地 WS 连接数。"""
        return len(self._clients)

    def register(self, ws: WebSocket) -> None:
        """把一条已通过握手的 WS 加入本地池。"""
        self._clients.add(ws)
        self._locks[ws] = asyncio.Lock()

    def unregister(self, ws: WebSocket) -> None:
        """从本地池摘除一条 WS。"""
        self._clients.discard(ws)
        self._locks.pop(ws, None)

    # ---- 生命周期 ----
    async def start(self) -> None:
        """启动订阅协程（``main.py::lifespan`` 调用）；失败降级为本地扇出。"""
        if self._started:
            return
        self._started = True
        self._sent_texts.clear()  # 每次应用生命周期重置去重窗口
        try:
            self._pubsub = get_redis().pubsub()
            await self._pubsub.subscribe(settings.monitor_redis_channel)
            self._sub_task = asyncio.create_task(self._subscribe_loop(), name="monitor-subscribe")
            logger.info(f"monitor 事件订阅已启动：{settings.monitor_redis_channel}")
        except Exception as exc:  # noqa: BLE001 —— Redis 不可用不阻断启动
            logger.warning(f"monitor Redis 订阅失败，降级为本地扇出（单实例仍可用）：{exc}")
            self._pubsub = None
            self._sub_task = None

    async def stop(self) -> None:
        """取消订阅协程、关闭 pubsub 与全部连接（``lifespan`` 关闭时调用）。"""
        if self._sub_task is not None:
            self._sub_task.cancel()
            with contextlib.suppress(BaseException):
                await self._sub_task
            self._sub_task = None
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await self._pubsub.unsubscribe(settings.monitor_redis_channel)
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()
            self._pubsub = None
        for ws in list(self._clients):
            with contextlib.suppress(Exception):
                await ws.close(code=1001)
        self._clients.clear()
        self._locks.clear()
        self._started = False

    async def _subscribe_loop(self) -> None:
        """消费 Redis 频道消息 → 本地扇出。"""
        if self._pubsub is None:
            return
        try:
            async for message in self._pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8", "ignore")
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    logger.warning("monitor 收到非法事件帧，已忽略")
                    continue
                await self.broadcast_local(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 订阅中断不影响进程其它功能
            logger.warning(f"monitor 订阅循环异常退出（降级为本地扇出）：{exc}")

    # ---- 发送 ----
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

    def add_listener(self, listener: Any) -> None:
        """注册一个「非 WS 扇出」的额外事件监听器（``listener(payload) -> Awaitable``）。

        用于把总线事件转给需要**定向路由**的消费者（如按用户可见性过滤的预警扇出）；
        同一监听器重复注册会被忽略（``in`` 对相同绑定方法判等）。监听器异常
        不影响 WS 扇出与其它监听器。
        """
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Any) -> None:
        """移除一个已注册的额外事件监听器（不存在则忽略）。"""
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    async def broadcast_local(self, payload: dict) -> None:
        """向本地所有连接发送文本帧；失败连接自动摘除；相同帧去重。

        去重后（即每个唯一帧仅一次）再依次通知额外监听器（如预警定向扇出），
        保证监听器既不会因 publish + 订阅回灌双发，也不会漏帧。
        """
        text = json.dumps(payload, ensure_ascii=False)
        if text in self._sent_texts:
            return
        self._sent_texts.append(text)

        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await self.send_to(ws, payload, text=text)
            except Exception:  # noqa: BLE001 —— 单连接失败不影响其它连接
                dead.append(ws)
        for ws in dead:
            self.unregister(ws)

        # 额外监听器：单监听器异常不影响其它监听器与 WS 扇出
        for listener in list(self._listeners):
            try:
                await listener(payload)
            except Exception as exc:  # noqa: BLE001 —— 监听器失败绝不影响主链路
                logger.warning(f"monitor 事件监听器执行失败（已忽略）：{type(exc).__name__}: {exc}")

    # ---- 快照 ----
    async def recent(self, limit: int) -> list[dict]:
        """读快照（Redis LIST）；Redis 不可用返回 ``[]``。"""
        if limit <= 0:
            return []
        try:
            raw = await get_redis().lrange(settings.monitor_recent_key, 0, limit - 1)
        except Exception as exc:  # noqa: BLE001 —— 快照不可用返回空
            logger.warning(f"monitor 快照读取失败（返回空）：{exc}")
            return []
        items: list[dict] = []
        for item in raw or []:
            if isinstance(item, (bytes, bytearray)):
                item = item.decode("utf-8", "ignore")
            try:
                items.append(json.loads(item))
            except (TypeError, ValueError):
                continue
        return items

    # ---- 发布 ----
    async def publish_event(self, event_type: str, data: dict) -> None:
        """统一发布：Redis publish + 快照；失败则本地扇出兜底；随后本地即时扇出（去重）。"""
        event = make_event(event_type, data)
        text = json.dumps(event, ensure_ascii=False)
        try:
            redis = get_redis()
            await redis.publish(settings.monitor_redis_channel, text)
            pipe = redis.pipeline()
            pipe.lpush(settings.monitor_recent_key, text)
            pipe.ltrim(settings.monitor_recent_key, 0, max(0, settings.monitor_recent_max - 1))
            pipe.expire(settings.monitor_recent_key, _SNAPSHOT_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 —— Redis 不可用 → 本地兜底
            logger.warning(f"monitor Redis 发布失败，本地兜底扇出：{exc}")
        # 本地即时扇出：单进程零延迟；订阅回路回灌的相同帧会被去重窗口丢弃
        await self.broadcast_local(event)


# 模块级单例
monitor_hub = MonitorHub()


async def publish_event(event_type: str, data: dict) -> None:
    """模块级便捷入口（供 detection / feedback / warning 调用）。"""
    await monitor_hub.publish_event(event_type, data)


async def _emit_detection_event(record_id: int, user_id: int) -> None:
    """``BackgroundTasks`` 任务：查记录 + 派生中文名 → 发布 ``detection.created``。

    任何异常仅记日志，**绝不影响检测主链路**。
    """
    try:
        db = SessionLocal()
        try:
            record = db.get(DetectionRecord, record_id)
            if record is None:
                logger.warning(f"检测事件发射：记录不存在 record_id={record_id}")
                return
            user = db.get(User, user_id)
            label = record.top_disease
            data = {
                "record_id": record.id,
                "user_id": user_id,
                "username": getattr(user, "username", None),
                "nickname": getattr(user, "nickname", None),
                "top_disease": label,
                "disease_cn": disease_cn_of(label),
                "crop": record.crop or derive_crop(label),
                "crop_cn": crop_cn_of(label),
                "severity_level": record.severity_level,
                "severity_label": severity.label_of(record.severity_level),
                "top_conf": record.top_conf,
                "thumb_url": storage.url_of(record.image_path),
                "created_at": to_utc_z(record.created_at) if record.created_at else _now_iso(),
            }
        finally:
            db.close()
        await publish_event("detection.created", data)
    except Exception as exc:  # noqa: BLE001 —— 事件发射失败绝不影响检测主链路
        logger.warning(f"检测事件发射失败（已忽略）：{type(exc).__name__}: {exc}")


__all__ = [
    "MonitorHub",
    "monitor_hub",
    "make_event",
    "publish_event",
    "_emit_detection_event",
]
