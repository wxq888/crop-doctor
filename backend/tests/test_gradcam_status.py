# -*- coding: utf-8 -*-
"""Grad-CAM 状态端点测试：仅当 ``status == done`` 才回热力图 URL。"""
import pytest

from app.models.detection import DetectionRecord
from tests.conftest import auth_headers

BASE = "/api/v1/detection"


def _set_gradcam(db_session, record_id: int, status: str, path: str | None) -> None:
    """直接改库，模拟后台任务回填结果。"""
    record = db_session.get(DetectionRecord, record_id)
    record.gradcam_status = status
    record.gradcam_path = path
    db_session.commit()


@pytest.fixture
def record(client, make_user, create_record) -> tuple[str, int]:
    """建一个用户 + 一条记录，返回 (token, record_id)。"""
    token, _ = make_user("cam_user")
    rec = create_record(token)
    return token, rec["id"]


def test_gradcam_pending_has_no_url(client, record) -> None:
    """pending → url 为 None。"""
    token, rid = record
    data = client.get(f"{BASE}/records/{rid}/gradcam", headers=auth_headers(token)).json()["data"]
    assert data["status"] == "pending"
    assert data["url"] is None


def test_gradcam_done_exposes_url(client, record, db_session) -> None:
    """done → 返回 /static/gradcam/... URL。"""
    token, rid = record
    _set_gradcam(db_session, rid, "done", f"gradcam/{rid}.jpg")

    data = client.get(f"{BASE}/records/{rid}/gradcam", headers=auth_headers(token)).json()["data"]
    assert data["status"] == "done"
    assert data["url"] == f"/static/gradcam/{rid}.jpg"


def test_gradcam_done_reflected_in_detail(client, record, db_session) -> None:
    """done 后，详情里的 gradcam_url 也应回填。"""
    token, rid = record
    _set_gradcam(db_session, rid, "done", f"gradcam/{rid}.jpg")

    detail = client.get(f"{BASE}/records/{rid}", headers=auth_headers(token)).json()["data"]
    assert detail["gradcam_status"] == "done"
    assert detail["gradcam_url"] == f"/static/gradcam/{rid}.jpg"


@pytest.mark.parametrize("status", ["failed", "skipped", "pending"])
def test_gradcam_non_done_hides_url(client, record, db_session, status) -> None:
    """非 done 状态（failed/skipped/pending）即使有 path 也不回 URL。"""
    token, rid = record
    _set_gradcam(db_session, rid, status, f"gradcam/{rid}.jpg")

    data = client.get(f"{BASE}/records/{rid}/gradcam", headers=auth_headers(token)).json()["data"]
    assert data["status"] == status
    assert data["url"] is None
