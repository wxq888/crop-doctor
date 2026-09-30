# -*- coding: utf-8 -*-
"""统一响应信封测试：**所有**端点（成功与失败）都必须返回 ``{code,message,data}``。

设计约定见 §5 / §6.1。任何"漏网"的非信封响应（裸 list、裸 dict、纯文本）
都应在此被拦截。
"""
import pytest

from tests.conftest import auth_headers, jpeg_bytes

AUTH = "/api/v1/auth"
DET = "/api/v1/detection"
WEA = "/api/v1/weather"


def _assert_envelope(resp) -> dict:
    """断言响应体恰为 {code,message,data} 三键，返回解析后的 body。"""
    ctype = resp.headers.get("content-type", "")
    assert "application/json" in ctype, f"非 JSON 响应：{ctype}"
    body = resp.json()
    assert isinstance(body, dict), f"响应体不是对象：{body!r}"
    assert set(body.keys()) == {"code", "message", "data"}, f"信封键不符：{body.keys()}"
    assert isinstance(body["code"], int)
    assert isinstance(body["message"], str)
    return body


@pytest.fixture
def tokens(client, make_user) -> dict:
    """准备一个已登录用户。"""
    token, user = make_user("envelope_user")
    return {"token": token, "user": user}


def test_health_envelope(client) -> None:
    """/health 也是信封（code=0）。"""
    body = _assert_envelope(client.get("/health"))
    assert body["code"] == 0


def test_auth_endpoints_envelope(client, tokens) -> None:
    """认证模块各端点成功/失败响应的信封。"""
    token = tokens["token"]
    # 注册成功 / 冲突
    _assert_envelope(client.post(f"{AUTH}/register", json={"username": "env_new", "password": "secret123"}))
    _assert_envelope(client.post(f"{AUTH}/register", json={"username": "env_new", "password": "secret123"}))
    # 登录成功 / 失败
    _assert_envelope(client.post(f"{AUTH}/login", json={"username": "env_new", "password": "secret123"}))
    _assert_envelope(client.post(f"{AUTH}/login", json={"username": "env_new", "password": "bad"}))
    # 资料读写 / 未登录
    _assert_envelope(client.get(f"{AUTH}/profile", headers=auth_headers(token)))
    _assert_envelope(client.get(f"{AUTH}/profile"))
    _assert_envelope(client.put(f"{AUTH}/profile", headers=auth_headers(token), json={"nickname": "x"}))
    # 改密成功 / 失败
    _assert_envelope(
        client.put(f"{AUTH}/password", headers=auth_headers(token),
                   json={"old_password": "bad", "new_password": "secret123"})
    )
    _assert_envelope(
        client.put(f"{AUTH}/password", headers=auth_headers(token),
                   json={"old_password": "secret123", "new_password": "secret456"})
    )


def test_detection_endpoints_envelope(client, tokens, create_record, stub_infer, stub_gradcam) -> None:
    """检测模块各端点成功/失败响应的信封。"""
    token = tokens["token"]
    rec = create_record(token)

    _assert_envelope(client.get(f"{DET}/records", headers=auth_headers(token)))
    _assert_envelope(client.get(f"{DET}/records/{rec['id']}", headers=auth_headers(token)))
    _assert_envelope(client.get(f"{DET}/records/{rec['id']}/gradcam", headers=auth_headers(token)))
    _assert_envelope(client.delete(f"{DET}/records/{rec['id']}", headers=auth_headers(token)))
    # 失败路径
    _assert_envelope(client.get(f"{DET}/records", headers=auth_headers("bad")))
    _assert_envelope(client.get(f"{DET}/records/9999", headers=auth_headers(token)))
    _assert_envelope(
        client.post(f"{DET}/image", headers=auth_headers(token),
                    files={"file": ("x.txt", b"x", "text/plain")})
    )
    stub_infer(spot_count=0)
    _assert_envelope(
        client.post(f"{DET}/image", headers=auth_headers(token),
                    files={"file": ("bg.jpg", jpeg_bytes(), "image/jpeg")})
    )


def test_weather_endpoints_envelope(client) -> None:
    """天气模块三端点（降级路径）响应的信封。"""
    _assert_envelope(client.get(f"{WEA}/now"))
    _assert_envelope(client.get(f"{WEA}/forecast"))
    _assert_envelope(client.get(f"{WEA}/spray-advice"))


def test_framework_errors_enveloped(client) -> None:
    """未知路由 / 方法不允许 也走统一信封。"""
    _assert_envelope(client.get("/api/v1/definitely/not/here"))
    _assert_envelope(client.patch("/health"))
