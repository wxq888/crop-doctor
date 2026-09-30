# -*- coding: utf-8 -*-
"""业务错误码与设计文档 §5.3 逐条对照测试。

逐条验证 code / HTTP 状态码映射，避免"错误码漂移"。
"""
import pytest

from app.core import exceptions as exc_mod
from tests.conftest import auth_headers, jpeg_bytes

AUTH = "/api/v1/auth"
DET = "/api/v1/detection"


def test_1001_username_exists(client) -> None:
    """1001：用户名已存在 → HTTP 400。"""
    payload = {"username": "errcode_dup", "password": "secret123"}
    assert client.post(f"{AUTH}/register", json=payload).status_code == 200
    resp = client.post(f"{AUTH}/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1001


def test_1002_bad_credentials(client) -> None:
    """1002：用户名或密码错误 → HTTP 401。"""
    client.post(f"{AUTH}/register", json={"username": "errcode_login", "password": "secret123"})
    for payload in (
        {"username": "errcode_login", "password": "wrong-pass"},
        {"username": "no-such-user", "password": "secret123"},
    ):
        resp = client.post(f"{AUTH}/login", json=payload)
        assert resp.status_code == 401
        assert resp.json()["code"] == 1002


def test_1003_missing_token(client) -> None:
    """1003：未登录 / Token 无效 → HTTP 401。"""
    resp = client.get(f"{AUTH}/profile")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


def test_1005_old_password_wrong(client, make_user) -> None:
    """1005：原密码错误 → HTTP 400。"""
    token, _ = make_user("errcode_pwd")
    resp = client.put(
        f"{AUTH}/password",
        headers=auth_headers(token),
        json={"old_password": "definitely-wrong", "new_password": "newsecret123"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1005


def test_2001_unsupported_image(client, make_user, stub_gradcam) -> None:
    """2001：图片格式不支持 → HTTP 400。"""
    token, _ = make_user("errcode_2001")
    resp = client.post(
        f"{DET}/image",
        headers=auth_headers(token),
        files={"file": ("note.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 2001


def test_2002_image_too_large(client, make_user, stub_gradcam) -> None:
    """2002：图片过大 → HTTP 413。"""
    from app.core.config import settings

    token, _ = make_user("errcode_2002")
    big = b"\xff" * (settings.max_upload_mb * 1024 * 1024 + 1)
    resp = client.post(
        f"{DET}/image",
        headers=auth_headers(token),
        files={"file": ("big.jpg", big, "image/jpeg")},
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == 2002


def test_2003_no_detection(client, make_user, stub_infer, stub_gradcam) -> None:
    """2003：未检出叶片 / 病害目标 → HTTP 422。"""
    stub_infer(spot_count=0)
    token, _ = make_user("errcode_2003")
    resp = client.post(
        f"{DET}/image",
        headers=auth_headers(token),
        files={"file": ("bg.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2003


def test_2004_record_not_found(client, make_user) -> None:
    """2004：检测记录不存在或无权访问 → HTTP 404。"""
    token, _ = make_user("errcode_2004")
    resp = client.get(f"{DET}/records/42424242", headers=auth_headers(token))
    assert resp.status_code == 404
    assert resp.json()["code"] == 2004


def test_9000_unknown_route_enveloped(client) -> None:
    """9000：框架级错误（未知路由）也走统一信封 → HTTP 404 / code 9000。"""
    resp = client.get("/api/v1/no/such/route")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 9000
    assert set(body.keys()) == {"code", "message", "data"}


def test_error_code_constants_match_design_table() -> None:
    """错误码常量与设计文档 §5.3 完全一致。"""
    expected = {
        "CODE_USERNAME_EXISTS": 1001,
        "CODE_BAD_CREDENTIALS": 1002,
        "CODE_UNAUTHORIZED": 1003,
        "CODE_FORBIDDEN": 1004,
        "CODE_OLD_PASSWORD_WRONG": 1005,
        "CODE_UNSUPPORTED_IMAGE": 2001,
        "CODE_IMAGE_TOO_LARGE": 2002,
        "CODE_NO_DETECTION": 2003,
        "CODE_RECORD_NOT_FOUND": 2004,
        "CODE_WEATHER_DEGRADED": 3001,
        "CODE_INTERNAL": 9000,
    }
    for name, value in expected.items():
        assert getattr(exc_mod, name) == value, f"{name} 应为 {value}"


@pytest.mark.parametrize(
    ("exc_cls", "code", "http_status"),
    [
        ("ModelLoadError", 9000, 500),
        ("InferenceError", 9000, 500),
        ("GradCamError", 9000, 500),
        ("GradCamDisabledError", 3001, 200),
    ],
)
def test_subclass_error_codes(exc_cls: str, code: int, http_status: int) -> None:
    """专用异常子类的 code / http_status 符合设计。"""
    instance = getattr(exc_mod, exc_cls)()
    assert instance.code == code
    assert instance.http_status == http_status
