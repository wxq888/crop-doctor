# -*- coding: utf-8 -*-
"""预警实时推送 WS（``WS /warning/ws/alerts``）测试。

重点（本任务核心）：**两用户可见性隔离** —— 全局广播推给所有在线连接，
定向预警**只推给归属用户**，绝无串号（A 的定向预警绝不能到 B）。

- 进程内用例（TestClient）：hello 可见性 / ping-pong / 连接数超限 4429；
- **真实网络层用例**：同进程起真实 uvicorn + 原生 ``websockets`` 客户端（真 TCP / 真握手），
  锁「两用户隔离」与「accept-first 下 4401/4403 可区分」两条契约。

事件发布走真实路径 ``publish_event("warning.created", {...})``：仅带 ``alert_id``，
由 ``AlertHub`` **回查库**取真实 ``user_id`` 再按 ``_visible_condition`` 语义定向扇出。
为让 WS 的 ``send`` 落在服务端事件循环内，发布协程经 ``run_coroutine_threadsafe``
调度到服务端 loop 执行（``_HOLDER["loop"]`` 在 fixture 内捕获）。
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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as native_ws_connect

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.models.warning import AlertRecord

WS_PATH = "/api/v1/warning/ws/alerts"
AUTH = "/api/v1/auth"


# ============================================================
# 造库工具
# ============================================================
def _create_user(db, username, password="secret123", role="user", status=1, nickname=None):
    """直接建库造用户。"""
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        status=status,
        nickname=nickname or username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_alert(db, *, user_id=None, disease="Tomato___Late_blight", risk="high", content="番茄晚疫病预警"):
    """直接落一条预警记录（``user_id=None`` 即全局广播）。"""
    record = AlertRecord(
        source="weather",
        disease=disease,
        risk_level=risk,
        content=content,
        user_id=user_id,
        location=None,
        is_read=0,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# ============================================================
# 进程内：hello 可见性 / 心跳 / 连接数超限
# ============================================================
def test_ws_hello_includes_visible_recent_only(client, make_user, db_session):
    """首帧 hello：信封契约 + heartbeat_seconds=25 + recent 仅含该用户可见预警。"""
    token, me = make_user("wsh_hello")
    _, other = make_user("wsh_other")
    g = _add_alert(db_session, user_id=None, disease="Apple___Apple_scab", content="全局")
    mine = _add_alert(db_session, user_id=me["id"], disease="Tomato___Late_blight", content="定向我")
    theirs = _add_alert(db_session, user_id=other["id"], disease="Grape___Black_rot", content="定向他")

    with client.websocket_connect(f"{WS_PATH}?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["v"] == 1
        assert hello["type"] == "hello"
        assert hello["data"]["server"] == "cropdoctor"
        assert hello["data"]["heartbeat_seconds"] == 25
        ids = {it["id"] for it in hello["data"]["recent"]}
        assert g.id in ids and mine.id in ids
        assert theirs.id not in ids, "hello 不得包含别人的定向预警"


def test_ws_ping_pong(client, make_user):
    """客户端 ping → 服务端 pong（信封风格）。"""
    token, _ = make_user("wsh_ping")
    with client.websocket_connect(f"{WS_PATH}?token={token}") as ws:
        ws.receive_json()  # hello
        ws.send_text(json.dumps({"type": "ping"}))
        pong = ws.receive_json()
        assert pong["v"] == 1 and pong["type"] == "pong"


def test_ws_no_token_close_4401(client):
    """无 token：accept-first 后 close 4401。"""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_invalid_token_close_4401(client):
    """伪造 token：close 4401。"""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{WS_PATH}?token=not-a-jwt") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_too_many_connections_close_4429(client, make_user, monkeypatch):
    """连接数超限（复用 MONITOR_MAX_CONNECTIONS）→ close 4429。"""
    token, _ = make_user("wsh_limit")
    monkeypatch.setattr(settings, "monitor_max_connections", 0)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{WS_PATH}?token={token}") as ws:
            ws.receive_text()
    assert exc.value.code == 4429


# ============================================================
# 真实网络层：文件型 SQLite（多连接）+ 真实 uvicorn + 原生 websockets 客户端
# ============================================================
def _free_port() -> int:
    """取一个空闲 TCP 端口。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def sqlite_file_db(tmp_path):
    """文件型 SQLite（**支持多连接**，供真实服务 + 测试线程各自安全取用会话）。"""
    eng = create_engine(
        f"sqlite:///{tmp_path / 'warning_ws.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        yield eng, factory
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


# 服务端事件循环持有器（供 run_coroutine_threadsafe 使用）
_HOLDER: dict = {}


@pytest.fixture
def real_server(sqlite_file_db, upload_dir, monkeypatch):
    """同进程真实 uvicorn：真 TCP / 真 HTTP 握手；DB 指向文件型 SQLite。"""
    _engine, session_factory = sqlite_file_db
    monkeypatch.setattr(settings, "gradcam_enabled", False)
    monkeypatch.setattr(settings, "weather_api_key", "")
    # 事件回查（_lookup_alert）与请求依赖都指向测试库
    monkeypatch.setattr("app.api.v1.warning.SessionLocal", lambda: session_factory())

    from app.main import app as fastapi_app

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    _HOLDER.clear()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
    )

    async def _serve_and_capture() -> None:
        _HOLDER["loop"] = asyncio.get_running_loop()
        await server.serve()

    thread = threading.Thread(
        target=lambda: asyncio.run(_serve_and_capture()),
        name="uvicorn-warning-net",
        daemon=True,
    )
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    assert server.started, "真实 uvicorn 启动失败"
    try:
        yield {"base": f"127.0.0.1:{port}", "factory": session_factory}
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        fastapi_app.dependency_overrides.pop(get_db, None)


def _ws_url(base: str, token: str | None) -> str:
    """构造原生客户端 WS URL。"""
    url = f"ws://{base}{WS_PATH}"
    return f"{url}?token={token}" if token else url


def _http_login(base: str, username: str, password: str) -> str:
    """向真实服务发 HTTP 登录，取 token。"""
    resp = httpx.post(
        f"http://{base}{AUTH}/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def _recv_json(ws, timeout=10) -> dict:
    """收一条 JSON 文本帧并解析。"""
    return json.loads(ws.recv(timeout=timeout))


def _recv_until(ws, event_type, max_frames=10, timeout=10) -> dict:
    """连续读帧直到命中 ``type``（跳过服务端 JSON 心跳 ping），返回该帧。"""
    for _ in range(max_frames):
        frame = _recv_json(ws, timeout=timeout)
        if frame.get("type") == event_type:
            return frame
    raise AssertionError(f"未在 {max_frames} 帧内收到 {event_type}")


def _publish_on_loop(alert_id: int, *, disease="Tomato___Late_blight", risk="high") -> None:
    """把 ``publish_event("warning.created")`` 调度到**服务端 loop** 上执行。

    载荷只带 ``alert_id``（真实契约：不含 user_id），由 AlertHub 回查库判定可见性。
    """
    from app.services.monitor import publish_event

    coro = publish_event(
        "warning.created",
        {
            "alert_id": alert_id,
            "source": "weather",
            "disease": disease,
            "disease_cn": None,
            "risk_level": risk,
            "location": None,
            "forecast_date": None,
            "content": "事件测试",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    loop = _HOLDER.get("loop")
    assert loop is not None, "服务端事件循环未捕获"
    asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=10)


def _native_close(base: str, query: str = "", timeout: int = 15) -> tuple[str, int | None]:
    """原生 websockets 客户端连真实服务，返回 (结果类型, close code)。

    - ``("hello", None)``：握手成功且收到首帧（未被拒）；
    - ``("closed", code)``：101 后被服务端按 code 关闭；
    - ``("handshake-failed", None)``：握手层直接失败（非 101）。
    """
    try:
        with native_ws_connect(
            f"ws://{base}{WS_PATH}{query}", open_timeout=15, close_timeout=10
        ) as ws:
            try:
                ws.recv(timeout=timeout)
                return ("hello", None)
            except ConnectionClosed as exc:
                return ("closed", exc.rcvd.code if exc.rcvd is not None else None)
    except Exception:  # noqa: BLE001 —— 握手层失败（非 101）
        return ("handshake-failed", None)


def test_real_network_close_codes_and_hello(real_server):
    """真实网络层：4401（无/伪造 token）与 4403（不存在/被禁用用户）可区分；正常用户收到 hello。"""
    base = real_server["base"]
    factory = real_server["factory"]
    db = factory()
    try:
        _create_user(db, "net_alice", "alicepass123")
        disabled = _create_user(db, "net_disabled", "disabledpass123", status=0)
        alice_t = _http_login(base, "net_alice", "alicepass123")
    finally:
        db.close()

    # 无 token → 4401
    assert _native_close(base, "") == ("closed", 4401), "无 token 应 4401"
    # 伪造 token → 4401
    assert _native_close(base, "?token=forged.jwt.value") == ("closed", 4401), "伪造 token 应 4401"
    # 被禁用用户（合法签名但 status=0）→ 4403
    disabled_t, _ = create_access_token(disabled.id, disabled.role)
    assert _native_close(base, f"?token={disabled_t}") == ("closed", 4403), "被禁用用户应 4403"
    # 用户不存在（合法签名但无此用户）→ 4403
    ghost_t, _ = create_access_token(999999, "user")
    assert _native_close(base, f"?token={ghost_t}") == ("closed", 4403), "用户不存在应 4403"
    # 正常用户 → 握手成功并收到 hello
    kind, code = _native_close(base, f"?token={alice_t}")
    assert kind == "hello", f"正常用户应握手成功，实际 {kind}/{code}"


def test_real_network_two_user_isolation(real_server):
    """**核心**：全局推全体；定向仅本人。A 的定向预警 B 一条都收不到（真实网络层）。"""
    base = real_server["base"]
    factory = real_server["factory"]
    db = factory()
    try:
        alice = _create_user(db, "iso_alice", "alicepass123")
        bob = _create_user(db, "iso_bob", "bobpass123")
        # 预置（hello 可见性）：全局 + 定向A + 定向B
        g = _add_alert(db, user_id=None, disease="Apple___Apple_scab", content="全局")
        ta = _add_alert(db, user_id=alice.id, disease="Tomato___Late_blight", content="定向A")
        tb = _add_alert(db, user_id=bob.id, disease="Grape___Black_rot", content="定向B")
        alice_t = _http_login(base, "iso_alice", "alicepass123")
        bob_t = _http_login(base, "iso_bob", "bobpass123")

        with (
            native_ws_connect(_ws_url(base, alice_t), open_timeout=15, close_timeout=10) as wa,
            native_ws_connect(_ws_url(base, bob_t), open_timeout=15, close_timeout=10) as wb,
        ):
            # ---- hello 可见性：A 见 全局 + 定向A；不见 定向B（B 对称）----
            hello_a = _recv_until(wa, "hello")
            hello_b = _recv_until(wb, "hello")
            ids_a = {it["id"] for it in hello_a["data"]["recent"]}
            ids_b = {it["id"] for it in hello_b["data"]["recent"]}
            assert g.id in ids_a and ta.id in ids_a and tb.id not in ids_a
            assert g.id in ids_b and tb.id in ids_b and ta.id not in ids_b

            # ---- ① 全局预警（user_id=None）→ A 与 B **都收到** ----
            g2 = _add_alert(db, user_id=None, disease="Potato___Early_blight", content="全局2")
            _publish_on_loop(g2.id, disease="Potato___Early_blight")
            fa = _recv_until(wa, "warning.created")
            fb = _recv_until(wb, "warning.created")
            assert fa["data"]["id"] == g2.id, f"A 应收到全局预警：{fa}"
            assert fb["data"]["id"] == g2.id, f"B 应收到全局预警：{fb}"
            assert fa["data"]["alert_id"] == g2.id and fb["type"] == "warning.created"

            # ---- ② 定向A 预警（user_id=A）→ **只有 A 收到，B 一条都收不到** ----
            t2 = _add_alert(db, user_id=alice.id, disease="Tomato___Late_blight", content="定向A2")
            _publish_on_loop(t2.id, disease="Tomato___Late_blight")
            fa2 = _recv_until(wa, "warning.created")
            assert fa2["data"]["id"] == t2.id, f"A 应收到自己的定向预警：{fa2}"
            # B 在超时窗口内不应收到任何数据帧（服务端 JSON 心跳 25s，窗口内不会有）
            with pytest.raises(TimeoutError):
                wb.recv(timeout=2.5)
    finally:
        db.close()
