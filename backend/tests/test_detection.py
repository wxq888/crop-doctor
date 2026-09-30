# -*- coding: utf-8 -*-
"""检测主链路端到端测试（推理与后台任务均以桩替换，保证确定性）。"""
import cv2
import numpy as np
import pytest

from app.services.yolo_infer import DetBox, DetectionResult
from tests.conftest import auth_headers

BASE = "/api/v1/detection"


def _make_jpeg(width: int = 64, height: int = 64) -> bytes:
    """生成一张可解码的 JPEG 字节流。"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (40, 140, 70)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _stub_infer(monkeypatch, spot_count: int = 1):
    """把 detector.infer 替换为确定性桩。"""

    def fake_infer(image_bgr, conf=None):
        if spot_count <= 0:
            return DetectionResult(
                boxes=[],
                top_label=None,
                top_conf=None,
                spot_count=0,
                area_ratio=0.0,
                annotated_bgr=image_bgr.copy(),
            )
        boxes = [
            DetBox(cls_id=0, label="Apple___Apple_scab", conf=0.93, bbox=[2, 2, 30, 30]),
            DetBox(cls_id=1, label="Apple___Black_rot", conf=0.40, bbox=[30, 30, 50, 50]),
        ][:spot_count]
        return DetectionResult(
            boxes=boxes,
            top_label=boxes[0].label,
            top_conf=boxes[0].conf,
            spot_count=len(boxes),
            area_ratio=0.02,
            annotated_bgr=image_bgr.copy(),
        )

    monkeypatch.setattr("app.services.yolo_infer.detector.infer", fake_infer)


def _stub_background(monkeypatch) -> None:
    """把后台 Grad-CAM 任务替换为 no-op。"""
    monkeypatch.setattr("app.api.v1.detection.run_gradcam_job", lambda record_id: None)


def test_detect_image_success(client, make_user, monkeypatch) -> None:
    """上传叶片图 → 返回分级/病害/URL，并落库头表与明细。"""
    _stub_infer(monkeypatch, spot_count=2)
    _stub_background(monkeypatch)
    token, _ = make_user("farmer1")

    resp = client.post(
        f"{BASE}/image",
        headers=auth_headers(token),
        files={"file": ("leaf.jpg", _make_jpeg(), "image/jpeg")},
        data={"location": "北京"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["top_disease"] == "Apple___Apple_scab"
    assert data["severity_level"] == 1
    assert data["severity_label"] == "轻微"
    assert data["spot_count"] == 2
    assert data["image_url"].startswith("/static/images/")
    assert data["annotated_url"].startswith("/static/annotated/")
    assert data["gradcam_status"] == "pending"
    assert len(data["details"]) == 2
    assert data["created_at"].endswith("Z")

    record_id = data["id"]

    # DB 校验
    from app.models.detection import DetectionDetail, DetectionRecord

    detail_resp = client.get(f"{BASE}/records/{record_id}", headers=auth_headers(token))
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["crop"] == "Apple"
    assert detail["location"] == "北京"
    assert detail["gradcam_url"] is None

    # 热力图状态端点
    gradcam_resp = client.get(f"{BASE}/records/{record_id}/gradcam", headers=auth_headers(token))
    assert gradcam_resp.status_code == 200
    assert gradcam_resp.json()["data"]["status"] == "pending"
    assert gradcam_resp.json()["data"]["url"] is None


def test_no_detection_returns_2003(client, make_user, monkeypatch) -> None:
    """全背景图（无框）→ 422 / 2003。"""
    _stub_infer(monkeypatch, spot_count=0)
    _stub_background(monkeypatch)
    token, _ = make_user("farmer2")

    resp = client.post(
        f"{BASE}/image",
        headers=auth_headers(token),
        files={"file": ("bg.jpg", _make_jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2003


def test_unsupported_type_returns_2001(client, make_user, monkeypatch) -> None:
    """非图片类型 → 400 / 2001。"""
    _stub_background(monkeypatch)
    token, _ = make_user("farmer3")

    resp = client.post(
        f"{BASE}/image",
        headers=auth_headers(token),
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 2001


def test_too_large_returns_2002(client, make_user, monkeypatch) -> None:
    """超大图片 → 413 / 2002。"""
    from app.core.config import settings

    _stub_background(monkeypatch)
    token, _ = make_user("farmer4")

    big = b"\xff" * (settings.max_upload_mb * 1024 * 1024 + 1024)
    resp = client.post(
        f"{BASE}/image",
        headers=auth_headers(token),
        files={"file": ("big.jpg", big, "image/jpeg")},
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == 2002


def test_data_isolation_between_users(client, make_user, monkeypatch) -> None:
    """用户 A 的记录对用户 B 不可见；B 越权取 A 的详情 → 404 / 2004。"""
    _stub_infer(monkeypatch, spot_count=1)
    _stub_background(monkeypatch)
    token_a, _ = make_user("userA")
    token_b, _ = make_user("userB")

    resp = client.post(
        f"{BASE}/image",
        headers=auth_headers(token_a),
        files={"file": ("leaf.jpg", _make_jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200
    record_id = resp.json()["data"]["id"]

    # A 能看到 1 条
    list_a = client.get(f"{BASE}/records", headers=auth_headers(token_a)).json()["data"]
    assert list_a["total"] == 1
    assert list_a["items"][0]["id"] == record_id
    assert list_a["items"][0]["thumb_url"].startswith("/static/images/")

    # B 看不到任何记录
    list_b = client.get(f"{BASE}/records", headers=auth_headers(token_b)).json()["data"]
    assert list_b["total"] == 0
    assert list_b["items"] == []

    # B 越权取 A 的详情 → 404 / 2004
    resp = client.get(f"{BASE}/records/{record_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404
    assert resp.json()["code"] == 2004

    # B 越权取热力图 → 404 / 2004
    resp = client.get(f"{BASE}/records/{record_id}/gradcam", headers=auth_headers(token_b))
    assert resp.status_code == 404

    # B 越权删除 → 404 / 2004
    resp = client.delete(f"{BASE}/records/{record_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404


def test_delete_own_record(client, make_user, monkeypatch) -> None:
    """删除本人记录后列表为空。"""
    _stub_infer(monkeypatch, spot_count=1)
    _stub_background(monkeypatch)
    token, _ = make_user("userC")

    resp = client.post(
        f"{BASE}/image",
        headers=auth_headers(token),
        files={"file": ("leaf.jpg", _make_jpeg(), "image/jpeg")},
    )
    record_id = resp.json()["data"]["id"]

    resp = client.delete(f"{BASE}/records/{record_id}", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"] is None

    list_resp = client.get(f"{BASE}/records", headers=auth_headers(token)).json()["data"]
    assert list_resp["total"] == 0

    # 再次取详情 → 404
    resp = client.get(f"{BASE}/records/{record_id}", headers=auth_headers(token))
    assert resp.status_code == 404


def test_list_pagination_and_filter(client, make_user, monkeypatch) -> None:
    """分页与按病害筛选。"""
    _stub_infer(monkeypatch, spot_count=1)
    _stub_background(monkeypatch)
    token, _ = make_user("userD")

    for _ in range(3):
        client.post(
            f"{BASE}/image",
            headers=auth_headers(token),
            files={"file": ("leaf.jpg", _make_jpeg(), "image/jpeg")},
        )

    page = client.get(f"{BASE}/records?page=1&page_size=2", headers=auth_headers(token)).json()["data"]
    assert page["total"] == 3
    assert page["page_size"] == 2
    assert page["pages"] == 2
    assert len(page["items"]) == 2

    filtered = client.get(
        f"{BASE}/records?disease=Apple___Apple_scab", headers=auth_headers(token)
    ).json()["data"]
    assert filtered["total"] == 3

    empty = client.get(
        f"{BASE}/records?disease=No___Such_disease", headers=auth_headers(token)
    ).json()["data"]
    assert empty["total"] == 0


def test_records_require_auth(client) -> None:
    """未登录访问记录 → 401 / 1003。"""
    resp = client.get(f"{BASE}/records")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


@pytest.mark.parametrize("bad_page_size", [0, 101])
def test_page_size_bounds(client, make_user, bad_page_size) -> None:
    """page_size 越界 → 422。"""
    token, _ = make_user(f"userE{bad_page_size}")
    resp = client.get(f"{BASE}/records?page_size={bad_page_size}", headers=auth_headers(token))
    assert resp.status_code == 422
