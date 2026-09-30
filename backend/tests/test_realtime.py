# -*- coding: utf-8 -*-
"""实时检测 WS（``WS /detection/ws/realtime``）测试。

覆盖：accept-first 鉴权（4401）、frame.result 协议、config 置信度、
背压 frame.skipped、单帧超限 4403、模型未就绪 error + close、心跳 ping/pong。
推理一律以确定性桩替换（与 test_detection.py 同一套路）。
"""
import json
import struct
import time

import cv2
import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from app.services import yolo_infer
from app.services.yolo_infer import DetBox, DetectionResult
from tests.conftest import auth_headers

BASE = "/api/v1/detection/ws/realtime"


def _make_jpeg(width: int = 64, height: int = 64) -> bytes:
    """生成一张可解码的 JPEG 字节流。"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (40, 140, 70)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _frame_msg(frame_id: int, jpeg: bytes) -> bytes:
    """按协议打包二进制帧：4 字节大端 frame_id + JPEG。"""
    return struct.pack(">I", frame_id) + jpeg


def _stub_infer(monkeypatch, conf_seen: list | None = None, sleep: float = 0.0):
    """把 detector.infer 替换为确定性桩；可选记录 conf / 模拟耗时。"""

    def fake_infer(image_bgr, conf=None):
        if conf_seen is not None:
            conf_seen.append(conf)
        if sleep:
            time.sleep(sleep)
        return DetectionResult(
            boxes=[DetBox(cls_id=0, label="Apple___Apple_scab", conf=0.93, bbox=[2, 2, 30, 30])],
            top_label="Apple___Apple_scab",
            top_conf=0.93,
            spot_count=1,
            area_ratio=0.02,
            annotated_bgr=image_bgr.copy(),
        )

    monkeypatch.setattr(yolo_infer.detector, "infer", fake_infer)
    return fake_infer


def _recv_json(ws) -> dict:
    """收一条 JSON 文本帧并解析。"""
    return json.loads(ws.receive_text())


# ============================================================
# 鉴权：accept-first + close 4401（无 token / 无效 token）
# ============================================================
def test_realtime_no_token_close_4401(client):
    """无 token：握手成功（accept-first）后被 close 4401，浏览器可观测。"""
    with client.websocket_connect(BASE) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4401


def test_realtime_invalid_token_close_4401(client):
    """无效 token：同样 close 4401。"""
    with client.websocket_connect(f"{BASE}?token=not-a-jwt") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4401


def test_realtime_normal_user_allowed(client, make_user, monkeypatch):
    """任何已登录用户可用（非 admin-only，与 monitor WS 不同）。"""
    token, _ = make_user("rtuser")
    _stub_infer(monkeypatch)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_bytes(_frame_msg(1, _make_jpeg()))
        msg = _recv_json(ws)
        assert msg["type"] == "frame.result"


# ============================================================
# 协议：frame.result / config / 心跳 / 非法帧
# ============================================================
def test_realtime_result_frame_protocol(client, make_user, monkeypatch):
    """frame.result：信封字段、frame_id 回显、bbox/label 结构齐全。"""
    token, _ = make_user("rtuser2")
    _stub_infer(monkeypatch)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_bytes(_frame_msg(7, _make_jpeg()))
        msg = _recv_json(ws)

        assert msg["v"] == 1
        assert msg["type"] == "frame.result"
        data = msg["data"]
        assert data["frame_id"] == 7
        assert data["count"] == 1
        assert isinstance(data["elapsed_ms"], int) and data["elapsed_ms"] >= 0

        box = data["boxes"][0]
        assert box["cls_id"] == 0
        assert box["label"] == "Apple___Apple_scab"
        # 中文名由 class-map 派生（缺失时回退原始类名，但必须是字符串）
        assert isinstance(box["label_cn"], str) and box["label_cn"]
        assert box["conf"] == pytest.approx(0.93)
        assert box["bbox"] == [2, 2, 30, 30]


def test_realtime_config_conf_passed_to_infer(client, make_user, monkeypatch):
    """首帧 config 消息可设置置信度阈值并透传到推理。"""
    token, _ = make_user("rtuser3")
    conf_seen: list = []
    _stub_infer(monkeypatch, conf_seen=conf_seen)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "config", "conf": 0.9}))
        ws.send_bytes(_frame_msg(1, _make_jpeg()))
        msg = _recv_json(ws)
        assert msg["type"] == "frame.result"
        assert conf_seen and conf_seen[-1] == pytest.approx(0.9)


def test_realtime_config_invalid_conf_ignored(client, make_user, monkeypatch):
    """非法 conf（越界/类型错）被忽略，回退默认 0.25。"""
    token, _ = make_user("rtuser4")
    conf_seen: list = []
    _stub_infer(monkeypatch, conf_seen=conf_seen)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "config", "conf": 42}))
        ws.send_text(json.dumps({"type": "config", "conf": "abc"}))
        ws.send_bytes(_frame_msg(1, _make_jpeg()))
        msg = _recv_json(ws)
        assert msg["type"] == "frame.result"
        assert conf_seen[-1] == pytest.approx(0.25)


def test_realtime_ping_pong(client, make_user):
    """心跳：客户端 ping → 服务端 pong（信封风格）。"""
    token, _ = make_user("rtuser5")
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        msg = _recv_json(ws)
        assert msg["v"] == 1 and msg["type"] == "pong"


def test_realtime_invalid_jpeg_error_frame(client, make_user, monkeypatch):
    """无法解码的二进制帧：回 error 帧，连接保持可用。"""
    token, _ = make_user("rtuser6")
    _stub_infer(monkeypatch)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_bytes(_frame_msg(1, b"\x00\x01\x02not-a-jpeg"))
        msg = _recv_json(ws)
        assert msg["type"] == "error"

        # 连接仍可用：下一张合法帧正常出结果
        ws.send_bytes(_frame_msg(2, _make_jpeg()))
        msg = _recv_json(ws)
        assert msg["type"] == "frame.result"
        assert msg["data"]["frame_id"] == 2


# ============================================================
# 背压：上一帧未算完 → 新帧丢弃并回 frame.skipped
# ============================================================
def test_realtime_backpressure_skip(client, make_user, monkeypatch):
    """连发多帧：只算一帧，其余被跳过并收到 frame.skipped。"""
    token, _ = make_user("rtuser7")
    _stub_infer(monkeypatch, sleep=0.5)  # 模拟 CPU 单帧数百 ms
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_bytes(_frame_msg(1, _make_jpeg()))
        ws.send_bytes(_frame_msg(2, _make_jpeg()))
        ws.send_bytes(_frame_msg(3, _make_jpeg()))

        results: list[dict] = []
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            kind_set = {m["type"] for m in results}
            if "frame.result" in kind_set and "frame.skipped" in kind_set:
                break
            results.append(_recv_json(ws))

        kinds = [m["type"] for m in results]
        assert kinds.count("frame.result") == 1, f"应只算 1 帧，实际：{kinds}"
        assert kinds.count("frame.skipped") >= 1, f"后续帧应被跳过，实际：{kinds}"
        skipped_ids = [m["data"]["frame_id"] for m in results if m["type"] == "frame.skipped"]
        assert 2 in skipped_ids or 3 in skipped_ids
        done = [m for m in results if m["type"] == "frame.result"][0]
        assert done["data"]["frame_id"] == 1


# ============================================================
# 防护：单帧超限 4403 / 模型未就绪 4503
# ============================================================
def _make_big_jpeg(min_bytes: int) -> bytes:
    """生成大于 min_bytes 的噪声 JPEG（随机纹理压缩率低）。"""
    size = 2500
    rng = np.random.default_rng(42)
    img = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    assert buf.size > min_bytes, "测试 JPEG 未达到目标体积"
    return buf.tobytes()


def test_realtime_oversized_frame_close_4403(client, make_user, monkeypatch):
    """单帧 > 1MB：先回 error 帧，再 close 4403。"""
    token, _ = make_user("rtuser8")
    big = _make_big_jpeg(1 * 1024 * 1024)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        ws.send_bytes(big)
        msg = _recv_json(ws)
        assert msg["type"] == "error"
        assert msg["data"]["code"] == 4403
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4403


def test_realtime_model_not_ready(client, make_user, monkeypatch):
    """模型未加载：回 error 帧 + close 4503。"""
    token, _ = make_user("rtuser9")
    monkeypatch.setattr(yolo_infer, "is_loaded", lambda: False)
    with client.websocket_connect(f"{BASE}?token={token}") as ws:
        msg = _recv_json(ws)
        assert msg["type"] == "error"
        assert msg["data"]["code"] == 4503
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4503
