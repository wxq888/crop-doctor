# -*- coding: utf-8 -*-
"""鉴权绕过专项测试（QA 独立补充）。

覆盖：无 token / 伪造 token / 篡改 payload / 错误签名密钥 / 过期 token /
被禁用用户（status=0）的 token / 指向不存在用户的 token，均须被拒绝为 1003；
并单测 ``get_current_admin`` 的非管理员拒绝（1004）。
"""
import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.core.config import settings
from app.core.deps import get_current_admin
from app.core.exceptions import BusinessError
from app.core.security import create_access_token
from app.models.user import User
from tests.conftest import auth_headers

BASE = "/api/v1/auth"


# ------------------------------------------------------------
# 辅助：篡改 JWT payload 但保留原签名
# ------------------------------------------------------------
def _tamper_payload(token: str, **claims) -> str:
    """修改 payload 中的字段但保留原签名，制造"签名不匹配"的伪造 token。"""
    header, payload, signature = token.split(".")

    def _b64d(seg: str) -> bytes:
        return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))

    def _b64e(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    data = json.loads(_b64d(payload))
    data.update(claims)
    new_payload = _b64e(json.dumps(data, separators=(",", ":")).encode())
    return f"{header}.{new_payload}.{signature}"


def _assert_1003(resp) -> None:
    """断言响应为 401 / 1003 且信封完整。"""
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["code"] == 1003
    assert set(body.keys()) == {"code", "message", "data"}


# ------------------------------------------------------------
# 各种无效 token
# ------------------------------------------------------------
@pytest.mark.parametrize(
    "token",
    [
        "not-a-real-token",
        "aaa.bbb.ccc",
        "",
        "Bearer",
    ],
)
def test_invalid_token_rejected(client, token) -> None:
    """非法 token → 401 / 1003。"""
    _assert_1003(client.get(f"{BASE}/profile", headers=auth_headers(token)))


def test_no_token_rejected(client) -> None:
    """无 Authorization 头 → 401 / 1003。"""
    _assert_1003(client.get(f"{BASE}/profile"))


def test_token_signed_with_wrong_key_rejected(client, make_user) -> None:
    """用错误密钥签名的 token → 401 / 1003。"""
    _, user = make_user("siguser")
    bad = jwt.encode(
        {
            "sub": str(user["id"]),
            "role": "user",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "a-totally-wrong-secret",
        algorithm=settings.jwt_algorithm,
    )
    _assert_1003(client.get(f"{BASE}/profile", headers=auth_headers(bad)))


def test_tampered_payload_rejected(client, make_user) -> None:
    """篡改 payload（换 sub）但保留原签名 → 401 / 1003。"""
    token, _ = make_user("tamperuser")
    tampered = _tamper_payload(token, sub="999999", role="admin")
    _assert_1003(client.get(f"{BASE}/profile", headers=auth_headers(tampered)))


def test_expired_token_rejected(client, make_user) -> None:
    """过期 token → 401 / 1003。"""
    _, user = make_user("expireuser")
    expired, _ = create_access_token(user["id"], "user", expires_minutes=-1)
    _assert_1003(client.get(f"{BASE}/profile", headers=auth_headers(expired)))


def test_token_for_nonexistent_user_rejected(client) -> None:
    """合法签名但指向不存在的用户 → 401 / 1003。"""
    token, _ = create_access_token(987654321, "user", expires_minutes=60)
    _assert_1003(client.get(f"{BASE}/profile", headers=auth_headers(token)))


def test_disabled_user_token_rejected(client, make_user, db_session) -> None:
    """被禁用用户（status=0）的合法 token → 401 / 1003。"""
    token, user = make_user("disableduser")

    # 确认初始可用
    assert client.get(f"{BASE}/profile", headers=auth_headers(token)).status_code == 200

    # 置为禁用
    row = db_session.get(User, user["id"])
    row.status = 0
    db_session.commit()

    _assert_1003(client.get(f"{BASE}/profile", headers=auth_headers(token)))
    # 禁用后亦不可登录
    resp = client.post(f"{BASE}/login", json={"username": "disableduser", "password": "secret123"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002


def test_valid_token_grants_access_to_all_protected_endpoints(client, make_user, create_record) -> None:
    """有效 token 可访问全部受保护端点（正向对照）。"""
    token, _ = make_user("validuser")
    rec = create_record(token)

    assert client.get(f"{BASE}/profile", headers=auth_headers(token)).status_code == 200
    assert client.get("/api/v1/detection/records", headers=auth_headers(token)).status_code == 200
    assert client.get(
        f"/api/v1/detection/records/{rec['id']}", headers=auth_headers(token)
    ).status_code == 200
    assert client.get(
        f"/api/v1/detection/records/{rec['id']}/gradcam", headers=auth_headers(token)
    ).status_code == 200


# ------------------------------------------------------------
# 1004：非管理员访问需管理员接口（直接单测依赖函数）
# ------------------------------------------------------------
def test_get_current_admin_rejects_normal_user() -> None:
    """普通用户调用 get_current_admin → BusinessError 1004 / 403。"""
    normal_user = User(id=1, username="normal", password_hash="x", role="user", status=1)
    with pytest.raises(BusinessError) as exc:
        get_current_admin(current_user=normal_user)
    assert exc.value.code == 1004
    assert exc.value.http_status == 403


def test_get_current_admin_accepts_admin() -> None:
    """管理员调用 get_current_admin 正常返回自身。"""
    admin = User(id=2, username="root", password_hash="x", role="admin", status=1)
    assert get_current_admin(current_user=admin) is admin
