# -*- coding: utf-8 -*-
"""monitor 接口：``WS /admin/ws/monitor``（仅 admin）+ 事件快照 REST。

设计依据：``docs/impl-pc-admin-v1.md`` §3.2 / §2.2。

WS 鉴权：浏览器 WebSocket 无法自定义请求头，采用 query 参数 ``?token=<jwt>``；
**握手前**校验 ``status==1 && role=='admin'``，失败按 close code 关闭且不 accept：
- ``4401`` 未授权（无 token / token 无效 / 用户不存在或被禁用）；
- ``4403`` 非管理员；
- ``4429`` 连接数超限（``MONITOR_MAX_CONNECTIONS``）。

心跳：服务端每 ``MONITOR_HEARTBEAT_SECONDS``(25s) 发 ``ping``；客户端回 ``pong`` 或发 ``ping``（服务端回 ``pong``）。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_admin
from app.core.response import ok
from app.core.security import decode_access_token
from app.models.user import User
from app.services.monitor import make_event, monitor_hub

router = APIRouter()

# WS 关闭码（对齐设计文档 §3.2）
CLOSE_UNAUTHORIZED = 4401  # 未授权 / token 无效 / 用户被禁用
CLOSE_FORBIDDEN = 4403  # 非管理员
CLOSE_TOO_MANY = 4429  # 连接数超限


def _resolve_ws_user(db: Session, token: str | None) -> User | None:
    """解析 query token → 校验 JWT → 查 users → 校验 ``status==1``。

    任一环节失败返回 ``None``（握手方据此 close 4401），不抛异常。
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except Exception:  # noqa: BLE001 —— token 无效一律按未授权处理
        return None
    user = db.get(User, user_id)
    if user is None or user.status != 1:
        return None
    return user


async def _heartbeat_loop(websocket: WebSocket) -> None:
    """服务端定时发 ``ping``；断开/异常时静默退出（由主循环负责清理）。"""
    interval = max(5, int(settings.monitor_heartbeat_seconds))
    try:
        while True:
            await asyncio.sleep(interval)
            await monitor_hub.send_to(websocket, make_event("ping", {}))
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001 —— 连接已断，主循环会清理
        return


async def _handle_client_frame(websocket: WebSocket, raw: str) -> None:
    """处理客户端帧：``pong`` 忽略；``ping`` 回 ``pong``；未知帧记 debug 后忽略。"""
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        logger.debug("monitor WS 收到非 JSON 帧，已忽略")
        return
    if not isinstance(frame, dict):
        return
    kind = frame.get("type")
    if kind == "ping":
        await monitor_hub.send_to(websocket, make_event("pong", {}))
    elif kind == "pong":
        return
    else:
        logger.debug(f"monitor WS 未知帧已忽略：{kind}")


@router.websocket("/ws/monitor")
async def ws_monitor(
    websocket: WebSocket,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """管理员实时事件流：**先 accept** → 再鉴权 → 失败按 close code 关闭。

    网络层要点（QA P2 修复）：Starlette 在 ``accept()`` 之前的 ``close(4401)``
    会被翻译成 HTTP 403 握手拒绝，浏览器拿不到自定义 close code；只有先
    accept 完成 101 握手，再 close 才能把 4401/4403/4429 送达客户端，
    前端才能按 code 区分提示与重连策略。
    """
    await websocket.accept()

    token = websocket.query_params.get("token")
    user = _resolve_ws_user(db, token)
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    if user.role != "admin":
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    if monitor_hub.connection_count >= int(settings.monitor_max_connections):
        await websocket.close(code=CLOSE_TOO_MANY)
        return

    monitor_hub.register(websocket)
    heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket), name="monitor-heartbeat")
    try:
        recent = await monitor_hub.recent(5)
        hello = make_event(
            "hello",
            {
                "server": "cropdoctor",
                "heartbeat_seconds": int(settings.monitor_heartbeat_seconds),
                "recent": recent,
            },
        )
        await monitor_hub.send_to(websocket, hello)
        while True:
            raw = await websocket.receive_text()
            await _handle_client_frame(websocket, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 —— 连接异常按断开处理
        logger.debug(f"monitor WS 异常关闭：{type(exc).__name__}: {exc}")
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(BaseException):
            await heartbeat_task
        monitor_hub.unregister(websocket)


@router.get("/monitor/events", summary="最近监控事件（断线补拉）")
async def monitor_events(
    current_admin: Annotated[User, Depends(get_current_admin)],
    limit: Annotated[int, Query(ge=1, le=100, description="补拉条数")] = 50,
) -> dict:
    """返回最近事件数组（Redis 快照）；Redis 不可用时返回空数组（不报错）。"""
    items = await monitor_hub.recent(limit)
    return ok({"items": items})
