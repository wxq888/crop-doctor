# -*- coding: utf-8 -*-
"""天气服务降级专项测试（永不 500 是硬要求）。

重点：
- ``WEATHER_API_KEY`` 为空 → 三接口均 200 + ``degraded=true``，且**不发起任何外部请求**；
- 上游超时 / 非 200 / 状态码非 200 / 缺字段 → 一律降级，不抛异常；
- ``days`` 越界 → 422（参数校验），合法边界 1 / 3 / 7 → 200；
- 天气接口无需登录即可访问。
"""
import httpx
import pytest

from app.core.config import settings

BASE = "/api/v1/weather"


class FakeRedis:
    """内存版 Redis 替身，隔离真实 Redis。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex=None):  # noqa: ANN001
        self.store[key] = value
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    """替换天气服务使用的 get_redis。"""
    fake = FakeRedis()
    monkeypatch.setattr("app.services.weather.get_redis", lambda: fake)
    return fake


def test_missing_key_degrades_without_any_request(client, fake_redis, monkeypatch) -> None:
    """密钥为空 → 三接口 200 + degraded=true，且绝不发起外部 HTTP 请求。"""
    monkeypatch.setattr(settings, "weather_api_key", "")

    def _boom() -> httpx.AsyncClient:  # 若被调用则说明代码错误地发起了请求
        raise AssertionError("WEATHER_API_KEY 为空时不应发起任何外部请求")

    monkeypatch.setattr("app.services.weather.make_client", _boom)

    now = client.get(f"{BASE}/now")
    assert now.status_code == 200
    assert now.json()["code"] == 0
    assert now.json()["data"]["degraded"] is True
    assert now.json()["data"]["temp"] is None

    forecast = client.get(f"{BASE}/forecast")
    assert forecast.status_code == 200
    assert forecast.json()["data"]["degraded"] is True
    assert forecast.json()["data"]["list"] == []

    advice = client.get(f"{BASE}/spray-advice")
    assert advice.status_code == 200
    body = advice.json()
    assert body["code"] == 0
    assert body["data"]["degraded"] is True
    assert body["data"]["advice"] == "暂无天气数据"
    assert body["data"]["next_rain_date"] is None


@pytest.mark.parametrize(
    "handler_kind",
    ["timeout", "http_500", "bad_code", "missing_field"],
)
def test_upstream_failures_degrade_not_500(client, fake_redis, monkeypatch, handler_kind) -> None:
    """上游各类失败 → 均降级为 200/degraded，绝不 500。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if handler_kind == "timeout":
            raise httpx.TimeoutException("timeout", request=request)
        if handler_kind == "http_500":
            return httpx.Response(500, json={"error": "oops"})
        if handler_kind == "bad_code":
            return httpx.Response(200, json={"code": "402", "now": {}})
        # missing_field：HTTP 200 且 code=200，但缺 "now"
        return httpx.Response(200, json={"code": "200"})

    monkeypatch.setattr(
        "app.services.weather.make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    for path in (f"{BASE}/now", f"{BASE}/forecast", f"{BASE}/spray-advice"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} 不应 500，实际 {resp.status_code}"
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["degraded"] is True


@pytest.mark.parametrize("days", [1, 3, 7])
def test_forecast_days_valid(client, fake_redis, monkeypatch, days) -> None:
    """days=1 / 3 / 7 合法。"""
    monkeypatch.setattr(settings, "weather_api_key", "")
    resp = client.get(f"{BASE}/forecast?days={days}")
    assert resp.status_code == 200


@pytest.mark.parametrize("days", [0, 8, -1])
def test_forecast_days_invalid(client, fake_redis, days) -> None:
    """days 越界（<1 或 >7）→ 422。"""
    resp = client.get(f"{BASE}/forecast?days={days}")
    assert resp.status_code == 422


def test_weather_endpoints_public(client, fake_redis) -> None:
    """天气三端点无需登录即可访问（设计未要求鉴权）。"""
    for path in (f"{BASE}/now", f"{BASE}/forecast", f"{BASE}/spray-advice"):
        assert client.get(path).status_code == 200
