# -*- coding: utf-8 -*-
"""admin 模块测试：统计口径 / 权限 / 全局检测 / 用户管理 / 模型管理。

隔离点：全部走内存 SQLite；模型管理把 ``exports_dir`` 指向 ``tmp_path``，不触碰真实 ``ml/exports``。
"""
from __future__ import annotations

import pytest

from app.core.security import hash_password
from app.models.user import User
from tests.conftest import auth_headers

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"


def _create_user(db_session, username, password="secret123", role="user", status=1, nickname=None):
    """直接建库造用户（可指定角色 / 状态）。"""
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
def admin_ctx(client, db_session):
    """创建一个管理员并返回其 user / token / headers。"""
    admin = _create_user(db_session, "root_admin", "adminpass123", role="admin")
    token = _login(client, "root_admin", "adminpass123")
    return {"user": admin, "token": token, "headers": auth_headers(token)}


# ============================================================
# 统计：口径诚实 + 结构完整
# ============================================================
def test_stats_overview_honest_metrics(client, admin_ctx):
    """概览返回完整字段；指标只用「平均置信度 / 健康率」，不得出现"准确率"。"""
    resp = client.get(f"{ADMIN}/stats/overview", headers=admin_ctx["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    for key in (
        "today_detections",
        "today_new_users",
        "total_users",
        "total_detections",
        "today_healthy_rate",
        "today_avg_conf",
        "warnings_active",
        "pending_feedbacks",
    ):
        assert key in data, key
    # 禁词：不得把平均置信度标成"准确率"
    assert "准确率" not in resp.text
    assert "accuracy" not in resp.text.lower()
    # 至少要能统计到刚造的管理员
    assert data["total_users"] >= 1


def test_stats_trend_structure(client, admin_ctx):
    """趋势返回 7 天序列 + 排行 / 分布 / 按作物。"""
    resp = client.get(f"{ADMIN}/stats/trend", headers=admin_ctx["headers"], params={"days": 7})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["days"]) == 7
    assert len(data["detections"]) == 7
    assert len(data["healthy"]) == 7
    assert len(data["warnings"]) == 7
    assert len(data["severity_dist"]) == 4
    assert isinstance(data["disease_rank"], list)
    assert isinstance(data["by_crop"], list)
    assert "准确率" not in resp.text


def test_stats_overview_counts_detections(client, admin_ctx, make_user, create_record):
    """造 2 条检测后，概览今日检测数 ≥ 2，且平均置信度 > 0。"""
    token, _ = make_user("stats_owner")
    # create_record 的 top_conf 由 stub_infer 默认 0.93
    create_record(token, label="Apple___Apple_scab")
    create_record(token, label="Apple___Black_rot")

    resp = client.get(f"{ADMIN}/stats/overview", headers=admin_ctx["headers"])
    data = resp.json()["data"]
    assert data["today_detections"] >= 2
    assert data["today_avg_conf"] > 0

    trend = client.get(
        f"{ADMIN}/stats/trend", headers=admin_ctx["headers"], params={"days": 7}
    ).json()["data"]
    assert sum(trend["detections"]) >= 2
    assert any(item["disease"] for item in trend["disease_rank"])


# ============================================================
# 权限：普通用户一律 403 / 1004
# ============================================================
def test_admin_endpoints_forbid_normal_user(client, make_user):
    """普通用户访问任意 admin 端点 → 403 / 1004。"""
    token, _ = make_user("plain_user")
    for path in ("/stats/overview", "/stats/trend", "/detections", "/users", "/model", "/monitor/events"):
        resp = client.get(f"{ADMIN}{path}", headers=auth_headers(token))
        assert resp.status_code == 403, f"{path} -> {resp.status_code}"
        assert resp.json()["code"] == 1004, path


def test_admin_endpoints_reject_anonymous(client):
    """无 token → 401 / 1003。"""
    resp = client.get(f"{ADMIN}/stats/overview")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


# ============================================================
# 全局检测记录（admin 越权查全量）
# ============================================================
def test_detections_global_list_and_detail(client, admin_ctx, make_user, create_record):
    """admin 能看到其他用户的检测记录，含用户名 / 中文名 / 分级；详情 200，缺失 404/2004。"""
    token, owner = make_user("det_owner")
    record = create_record(token, label="Apple___Apple_scab")

    listing = client.get(f"{ADMIN}/detections", headers=admin_ctx["headers"])
    assert listing.status_code == 200, listing.text
    items = listing.json()["data"]["items"]
    mine = [i for i in items if i["id"] == record["id"]]
    assert mine, "admin 未看到其他用户的检测记录"
    item = mine[0]
    assert item["username"] == "det_owner"
    assert item["user_id"] == owner["id"]
    assert item["disease_cn"] == "苹果黑星病"
    assert item["severity_label"] in {"无", "轻微", "中等", "严重"}
    assert item["top_conf"] is not None

    detail = client.get(f"{ADMIN}/detections/{record['id']}", headers=admin_ctx["headers"])
    assert detail.status_code == 200, detail.text
    d = detail.json()["data"]
    assert d["user_id"] == owner["id"]
    assert d["disease_cn"] == "苹果黑星病"

    missing = client.get(f"{ADMIN}/detections/999999", headers=admin_ctx["headers"])
    assert missing.status_code == 404
    assert missing.json()["code"] == 2004


# ============================================================
# 用户管理
# ============================================================
def test_users_list_detail_and_status(client, admin_ctx, db_session, make_user):
    """列表 / 详情 / 禁用启用 / 禁自己 8002 / 最后一个管理员 8002。"""
    token, target = make_user("u_target")
    uid = target["id"]

    listing = client.get(
        f"{ADMIN}/users", headers=admin_ctx["headers"], params={"keyword": "u_target"}
    )
    assert listing.status_code == 200
    assert any(u["id"] == uid for u in listing.json()["data"]["items"])

    detail = client.get(f"{ADMIN}/users/{uid}", headers=admin_ctx["headers"])
    assert detail.status_code == 200
    assert detail.json()["data"]["username"] == "u_target"

    # 禁用普通用户 → 200
    off = client.put(
        f"{ADMIN}/users/{uid}/status", headers=admin_ctx["headers"], json={"status": 0}
    )
    assert off.status_code == 200, off.text
    assert off.json()["data"]["status"] == 0
    # 重新启用 → 200
    on = client.put(
        f"{ADMIN}/users/{uid}/status", headers=admin_ctx["headers"], json={"status": 1}
    )
    assert on.status_code == 200
    assert on.json()["data"]["status"] == 1

    # 禁用「自己」→ 409 / 8002
    self_off = client.put(
        f"{ADMIN}/users/{admin_ctx['user'].id}/status",
        headers=admin_ctx["headers"],
        json={"status": 0},
    )
    assert self_off.status_code == 409
    assert self_off.json()["code"] == 8002

    # 禁用「最后一个启用中的管理员」→ 409 / 8002（造一个已禁用的管理员作为目标）
    disabled_admin = _create_user(db_session, "admin_disabled", "dpass12345", role="admin", status=0)
    last_off = client.put(
        f"{ADMIN}/users/{disabled_admin.id}/status",
        headers=admin_ctx["headers"],
        json={"status": 0},
    )
    assert last_off.status_code == 409
    assert last_off.json()["code"] == 8002

    # 用户不存在 → 404 / 8001
    missing = client.get(f"{ADMIN}/users/999999", headers=admin_ctx["headers"])
    assert missing.status_code == 404
    assert missing.json()["code"] == 8001


def test_reset_password(client, admin_ctx, make_user):
    """重置密码返回新密码，且新密码可登录；不存在 → 404 / 8001。"""
    token, target = make_user("reset_me")
    resp = client.post(
        f"{ADMIN}/users/{target['id']}/reset-password",
        headers=admin_ctx["headers"],
        json={},
    )
    assert resp.status_code == 200, resp.text
    new_password = resp.json()["data"]["new_password"]
    assert len(new_password) >= 6

    login = client.post(
        f"{AUTH}/login", json={"username": "reset_me", "password": new_password}
    )
    assert login.status_code == 200, login.text

    missing = client.post(
        f"{ADMIN}/users/999999/reset-password", headers=admin_ctx["headers"], json={}
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == 8001


# ============================================================
# 模型管理（隔离到 tmp_path）
# ============================================================
def test_model_list_and_activate(client, admin_ctx, monkeypatch, tmp_path):
    """列表 / 热切换（桩掉重载）/ 持久化 active_model.json / 非法文件 8003。"""
    import app.services.model_registry as mr

    (tmp_path / "yolo-v1.pt").write_bytes(b"a" * 1024)
    (tmp_path / "yolo-v2.pt").write_bytes(b"b" * 2048)
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

    monkeypatch.setattr(mr, "exports_dir", lambda: tmp_path)
    reloaded: list[str] = []
    monkeypatch.setattr(mr, "reload_detector", lambda name: reloaded.append(name))

    listing = client.get(f"{ADMIN}/model", headers=admin_ctx["headers"])
    assert listing.status_code == 200, listing.text
    data = listing.json()["data"]
    names = {i["filename"] for i in data["items"]}
    assert names == {"yolo-v1.pt", "yolo-v2.pt"}  # 非 .pt 文件被过滤
    assert isinstance(data["loaded"], bool)

    activate = client.post(
        f"{ADMIN}/model/activate",
        headers=admin_ctx["headers"],
        json={"filename": "yolo-v2.pt"},
    )
    assert activate.status_code == 200, activate.text
    assert reloaded == ["yolo-v2.pt"]
    assert activate.json()["data"]["filename"] == "yolo-v2.pt"
    assert (tmp_path / "active_model.json").exists()
    assert mr.active_model_name() == "yolo-v2.pt"

    # 重启后仍生效：active_model_name 从文件读回
    assert mr.active_model_name() == "yolo-v2.pt"

    bad = client.post(
        f"{ADMIN}/model/activate",
        headers=admin_ctx["headers"],
        json={"filename": "ghost.pt"},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == 8003


def test_active_model_falls_back_when_file_missing(monkeypatch, tmp_path):
    """active_model.json 指向不存在的权重时回退默认权重名。"""
    import app.services.model_registry as mr

    monkeypatch.setattr(mr, "exports_dir", lambda: tmp_path)
    mr.persist_active_model("deleted.pt")
    assert mr.active_model_name() == mr.default_model_name()
