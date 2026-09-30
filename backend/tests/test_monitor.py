# -*- coding: utf-8 -*-
"""monitor 模块测试：WS 握手鉴权 / hello / 心跳参数 / 事件扇出 / Redis 兜底 / 快照。

- WS 集成用 ``TestClient.websocket_connect``（进程内）；
- **真实网络层用例**：同进程起真实 uvicorn + 原生 ``websockets`` 客户端（不走
  ``WebSocketTestSession``），锁住「4401 / 4403 在网络层可区分」这一契约（QA P2 回归锁）；
- 事件扇出经真实检测主链路触发（后台任务）；
- Redis 不可用用桩 ``get_redis`` 抛错验证本地兜底。
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as native_ws_connect

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.services.monitor import MonitorHub, make_event
from tests.conftest import auth_headers

AUTH = "/api/v1/auth"
WS_PATH = "/api/v1/admin/ws/monitor"
EVENTS_PATH = "/api/v1/admin/monitor/events"


def _create_user(db_session, username, password="secret123", role="user", status=1, nickname=None):
    """直接建库造用户。"""
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        status=status,
        nickname=nickname or username,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client, username, password="secret123"):
    """登录并返回 access_token。"""
    resp = client.post(f"{AUTH}/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


@pytest.fixture
def admin_token(client, db_session):
    """创建一个管理员并返回其 token。"""
    _create_user(db_session, "ws_admin", "adminpass123", role="admin")
    return _login(client, "ws_admin", "adminpass123")


def _recv_until(ws, event_type, max_frames=20):
    """从 WS 连续读帧，直到命中指定 ``type``（跳过 ping 等），返回该帧。"""
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame.get("type") == event_type:
            return frame
    raise AssertionError(f"未在 {max_frames} 帧内收到 {event_type}")


# ============================================================
# 握手鉴权（进程内 TestClient）
# ============================================================
def test_ws_hello_for_admin(client, admin_token):
    """admin token 连上 → 首帧 hello，含 heartbeat_seconds=25 与 recent 列表。"""
    with client.websocket_connect(f"{WS_PATH}?token={admin_token}") as ws:
        frame = ws.receive_json()
        assert frame["v"] == 1
        assert frame["type"] == "hello"
        assert frame["data"]["server"] == "cropdoctor"
        assert frame["data"]["heartbeat_seconds"] == 25
        assert isinstance(frame["data"]["recent"], list)


def test_ws_rejected_without_token(client):
    """无 token → 服务端 accept 后按 close(4401) 关闭。"""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()
    assert excinfo.value.code == 4401


def test_ws_rejected_with_invalid_token(client):
    """伪造 token → close(4401)。"""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"{WS_PATH}?token=not-a-real-jwt") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4401


def test_ws_rejected_for_normal_user(client, make_user):
    """普通用户 token → close(4403)（非管理员）。"""
    token, _ = make_user("ws_plain")
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"{WS_PATH}?token={token}") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4403


def test_ws_rejected_when_too_many_connections(client, admin_token, monkeypatch):
    """连接数超限 → close(4429)。"""
    monkeypatch.setattr(settings, "monitor_max_connections", 0)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"{WS_PATH}?token={admin_token}") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4429


# ============================================================
# 真实网络层（QA P2 回归锁）：真实 uvicorn + 原生 websockets 客户端
# ============================================================
def _free_port() -> int:
    """取一个空闲 TCP 端口。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def real_server(db_session, upload_dir, monkeypatch):
    """在**同进程**起真实 uvicorn（真 TCP / 真 HTTP 握手）。

    DB 经 ``dependency_overrides`` 指向内存 SQLite（同进程生效），上传目录隔离到 tmp。
    """
    monkeypatch.setattr(settings, "gradcam_enabled", False)
    monkeypatch.setattr(settings, "weather_api_key", "")

    from app.main import app as fastapi_app

    def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="uvicorn-net-test", daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    assert server.started, "真实 uvicorn 启动失败"
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=15)
    fastapi_app.dependency_overrides.pop(get_db, None)


def _http_login(base: str, username: str, password: str) -> str:
    """向真实服务发 HTTP 登录，取 token。"""
    resp = httpx.post(
        f"http://{base}{AUTH}/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def _native_close_code(base: str, query: str) -> tuple[str, int | None]:
    """用**原生 websockets 客户端**连真实服务，返回 (结果类型, close code)。

    - ``("hello", None)``：连接成功且收到首帧（未被拒）；
    - ``("closed", code)``：握手 101 成功后被服务端按 code 关闭；
    - ``("handshake-failed", None)``：握手层直接失败（HTTP 非 101）。
    """
    url = f"ws://{base}{WS_PATH}{query}"
    try:
        with native_ws_connect(url, open_timeout=15, close_timeout=10) as ws:
            try:
                ws.recv(timeout=15)
                return ("hello", None)
            except ConnectionClosed as exc:
                return ("closed", exc.rcvd.code if exc.rcvd is not None else None)
    except Exception:  # noqa: BLE001 —— 握手层失败（非 101）
        return ("handshake-failed", None)


def test_real_network_close_codes_distinguishable(real_server, db_session):
    """真实网络层：4401（未授权）与 4403（非管理员）必须可区分；admin 正常收到 hello。"""
    _create_user(db_session, "net_admin", "adminpass123", role="admin")
    _create_user(db_session, "net_user", "userpass123")
    admin_t = _http_login(real_server, "net_admin", "adminpass123")
    user_t = _http_login(real_server, "net_user", "userpass123")

    # 1) admin → 握手成功并收到 hello（未被拒）
    kind, code = _native_close_code(real_server, f"?token={admin_t}")
    assert kind == "hello", f"admin 应握手成功，实际 {kind}/{code}"

    # 2) 无 token → close 4401
    kind, code = _native_close_code(real_server, "")
    assert (kind, code) == ("closed", 4401), f"无 token 应 4401，实际 {kind}/{code}"

    # 3) 伪造 token → close 4401
    kind, code = _native_close_code(real_server, "?token=forged.jwt.value")
    assert (kind, code) == ("closed", 4401), f"伪造 token 应 4401，实际 {kind}/{code}"

    # 4) 普通用户 → close 4403（与 4401 可区分）
    kind, code = _native_close_code(real_server, f"?token={user_t}")
    assert (kind, code) == ("closed", 4403), f"普通用户应 4403，实际 {kind}/{code}"

    # 5) 汇总断言：三类结果两两可区分
    assert 4401 != 4403


# ============================================================
# 事件扇出（真实检测链路 → WS）
# ============================================================
def test_ws_receives_detection_event(
    client, admin_token, db_session, engine, make_user, create_record, monkeypatch
):
    """admin 连上 → 触发一次检测 → WS 收到 detection.created（含中文名/分级/缩略图）。"""
    # 让后台发射任务读取「测试内存库」而非真实 MySQL
    test_sessionmaker = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr("app.services.monitor.SessionLocal", lambda: test_sessionmaker())

    token, owner = make_user("det_event_user")
    with client.websocket_connect(f"{WS_PATH}?token={admin_token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        record = create_record(token, label="Apple___Apple_scab")
        event = _recv_until(ws, "detection.created")
        data = event["data"]
        assert data["record_id"] == record["id"]
        assert data["user_id"] == owner["id"]
        assert data["username"] == "det_event_user"
        assert data["disease_cn"] == "苹果黑星病"
        assert data["crop_cn"] == "苹果"
        assert data["severity_label"] in {"无", "轻微", "中等", "严重"}
        assert data["thumb_url"]


def test_monitor_events_endpoint_returns_items(client, admin_token):
    """GET /admin/monitor/events → 200，data.items 为列表（Redis 快照，降级为空也不报错）。"""
    resp = client.get(EVENTS_PATH, headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert isinstance(data["items"], list)


def test_monitor_events_requires_admin(client, make_user):
    """普通用户访问快照端点 → 403 / 1004。"""
    token, _ = make_user("evt_plain")
    resp = client.get(EVENTS_PATH, headers=auth_headers(token))
    assert resp.status_code == 403
    assert resp.json()["code"] == 1004


# ============================================================
# Redis 降级兜底（纯单元）
# ============================================================
class _FakeWS:
    """最小 WS 替身：记录下发的文本帧。"""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:  # pragma: no cover - 兜底接口
        return None


def test_publish_event_local_fallback_when_redis_down(monkeypatch):
    """Redis 抛错时 publish_event 仍向本地连接扇出（WS 不挂）。"""
    import app.services.monitor as mon

    hub = MonitorHub()
    fake = _FakeWS()
    hub.register(fake)

    def _boom():  # noqa: ANN202
        raise RuntimeError("redis down")

    monkeypatch.setattr(mon, "get_redis", _boom)

    asyncio.run(hub.publish_event("detection.created", {"record_id": 7, "disease_cn": "苹果黑星病"}))

    assert len(fake.sent) == 1, "Redis 不可用时本地兜底未生效"
    frame = json.loads(fake.sent[0])
    assert frame["v"] == 1
    assert frame["type"] == "detection.created"
    assert frame["data"]["record_id"] == 7
    hub.unregister(fake)


def test_recent_returns_empty_when_redis_down(monkeypatch):
    """Redis 不可用时快照读取返回空数组（不抛错）。"""
    import app.services.monitor as mon

    hub = MonitorHub()

    def _boom():  # noqa: ANN202
        raise RuntimeError("redis down")

    monkeypatch.setattr(mon, "get_redis", _boom)
    assert asyncio.run(hub.recent(10)) == []


def test_broadcast_local_dedup():
    """相同事件帧只广播一次（防 publish + 订阅回灌双发）。"""
    hub = MonitorHub()
    fake = _FakeWS()
    hub.register(fake)
    event = make_event("ping", {})
    asyncio.run(hub.broadcast_local(event))
    asyncio.run(hub.broadcast_local(event))
    assert len(fake.sent) == 1
    hub.unregister(fake)


def test_make_event_envelope():
    """事件信封字段与冻结契约一致。"""
    event = make_event("hello", {"a": 1})
    assert set(event.keys()) == {"v", "type", "ts", "data"}
    assert event["v"] == 1
    assert event["ts"].endswith("Z")
