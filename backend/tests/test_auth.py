# -*- coding: utf-8 -*-
"""认证模块端到端测试。"""
from tests.conftest import auth_headers

BASE = "/api/v1/auth"


def test_register_login_profile_flow(client) -> None:
    """注册 → 登录 → 带 token 访问资料：全链路 200。"""
    resp = client.post(f"{BASE}/register", json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "alice"
    assert body["data"]["role"] == "user"

    resp = client.post(f"{BASE}/login", json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 10080 * 60
    token = data["access_token"]

    resp = client.get(f"{BASE}/profile", headers=auth_headers(token))
    assert resp.status_code == 200
    profile = resp.json()["data"]
    assert profile["username"] == "alice"
    # 时间统一 UTC，ISO-8601 带 Z
    assert profile["created_at"].endswith("Z")


def test_duplicate_username_returns_1001(client) -> None:
    """重复用户名 → 400 / 1001。"""
    payload = {"username": "bob", "password": "secret123"}
    assert client.post(f"{BASE}/register", json=payload).status_code == 200
    resp = client.post(f"{BASE}/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1001


def test_wrong_password_returns_1002(client) -> None:
    """错误密码 → 401 / 1002。"""
    client.post(f"{BASE}/register", json={"username": "carol", "password": "secret123"})
    resp = client.post(f"{BASE}/login", json={"username": "carol", "password": "wrongpass"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002


def test_missing_token_returns_1003(client) -> None:
    """无 token → 401 / 1003。"""
    resp = client.get(f"{BASE}/profile")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


def test_invalid_token_returns_1003(client) -> None:
    """非法 token → 401 / 1003。"""
    resp = client.get(f"{BASE}/profile", headers=auth_headers("not-a-real-token"))
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


def test_update_profile(client, make_user) -> None:
    """更新昵称 / 头像。"""
    token, _ = make_user("dave")
    resp = client.put(
        f"{BASE}/profile",
        headers=auth_headers(token),
        json={"nickname": "大卫", "avatar": "/static/a.png"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["nickname"] == "大卫"
    assert data["avatar"] == "/static/a.png"


def test_change_password_and_old_fails(client, make_user) -> None:
    """改密后旧密码失效、新密码可登录。"""
    token, _ = make_user("erin", password="oldpass123")

    # 原密码错误 → 1005
    resp = client.put(
        f"{BASE}/password",
        headers=auth_headers(token),
        json={"old_password": "bad", "new_password": "newpass123"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1005

    # 正确改密
    resp = client.put(
        f"{BASE}/password",
        headers=auth_headers(token),
        json={"old_password": "oldpass123", "new_password": "newpass123"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] is None

    # 旧密码失效
    resp = client.post(f"{BASE}/login", json={"username": "erin", "password": "oldpass123"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002

    # 新密码可用
    resp = client.post(f"{BASE}/login", json={"username": "erin", "password": "newpass123"})
    assert resp.status_code == 200
