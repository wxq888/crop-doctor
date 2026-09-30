# -*- coding: utf-8 -*-
"""天气服务测试：降级路径 + MockTransport 成功路径 + Redis 缓存命中。"""
import httpx
import pytest

from app.core.config import settings

BASE = "/api/v1/weather"


class FakeRedis:
    """内存版 Redis 替身，用于隔离真实 Redis。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex=None):
        self.store[key] = value
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    """把天气服务用的 get_redis 替换为内存替身。"""
    fake = FakeRedis()
    monkeypatch.setattr("app.services.weather.get_redis", lambda: fake)
    return fake


def test_degraded_when_no_api_key(client, fake_redis, monkeypatch) -> None:
    """密钥为空 → 三接口均 200、degraded=true、服务不 500。"""
    monkeypatch.setattr(settings, "weather_api_key", "")

    now = client.get(f"{BASE}/now")
    assert now.status_code == 200
    assert now.json()["code"] == 0
    assert now.json()["data"]["degraded"] is True

    forecast = client.get(f"{BASE}/forecast")
    assert forecast.status_code == 200
    assert forecast.json()["data"]["degraded"] is True
    assert forecast.json()["data"]["list"] == []

    advice = client.get(f"{BASE}/spray-advice")
    assert advice.status_code == 200
    assert advice.json()["data"]["degraded"] is True
    assert advice.json()["data"]["advice"] == "暂无天气数据"


def test_degraded_on_network_error(client, fake_redis, monkeypatch) -> None:
    """有密钥但网络失败 → 仍 200、degraded=true。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(
        "app.services.weather.make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    resp = client.get(f"{BASE}/now")
    assert resp.status_code == 200
    assert resp.json()["data"]["degraded"] is True


def test_success_and_cache_hit(client, fake_redis, monkeypatch) -> None:
    """有密钥且接口正常 → 正常数据；二次调用命中 Redis 缓存。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        path = request.url.path
        if path.endswith("/now"):
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "now": {
                        "text": "晴",
                        "temp": "25",
                        "humidity": "40",
                        "windDir": "北风",
                        "windScale": "3",
                        "obsTime": "2025-06-01T03:00+08:00",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": "200",
                "daily": [
                    {
                        "fxDate": "2025-06-01",
                        "tempMax": "30",
                        "tempMin": "20",
                        "textDay": "小雨",
                        "textNight": "多云",
                        "humidity": "55",
                        "precip": "1.2",
                    },
                    {
                        "fxDate": "2025-06-02",
                        "tempMax": "31",
                        "tempMin": "21",
                        "textDay": "晴",
                        "textNight": "晴",
                        "humidity": "50",
                        "precip": "0.0",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.weather.make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    resp = client.get(f"{BASE}/now")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["text"] == "晴"
    assert data["temp"] == 25.0
    assert data["degraded"] is False
    assert calls["count"] == 1

    # 二次调用：命中缓存，不再请求外部接口
    resp2 = client.get(f"{BASE}/now")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["text"] == "晴"
    assert calls["count"] == 1

    # 预报 + 施药建议
    forecast = client.get(f"{BASE}/forecast?days=2").json()["data"]
    assert forecast["degraded"] is False
    assert len(forecast["list"]) == 2
    assert forecast["list"][0]["date"] == "2025-06-01"

    advice = client.get(f"{BASE}/spray-advice").json()["data"]
    assert advice["degraded"] is False
    assert advice["next_rain_date"] == "2025-06-01"
    assert "降雨" in advice["advice"]


def test_spray_advice_no_rain(client, fake_redis, monkeypatch) -> None:
    """预报无降雨 → 建议文案提示适宜施药。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "200",
                "daily": [
                    {
                        "fxDate": "2025-06-01",
                        "tempMax": "30",
                        "tempMin": "20",
                        "textDay": "晴",
                        "textNight": "晴",
                        "humidity": "50",
                        "precip": "0.0",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.weather.make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    advice = client.get(f"{BASE}/spray-advice").json()["data"]
    assert advice["degraded"] is False
    assert advice["next_rain_date"] is None
    assert "适宜施药" in advice["advice"]


# ---------------------------------------------------------------------------
# 天气详情页扩展：now 新字段 / 7d 预报 / 24h 逐时
# ---------------------------------------------------------------------------


def _mock_transport(responder):
    """构造 MockTransport 客户端替身的快捷方式。"""
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(responder))


def test_now_extended_fields(client, fake_redis, monkeypatch) -> None:
    """now 接口返回体感/降水/气压/能见度/云量/露点/观测时间 7 个扩展字段。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v7/weather/now")
        return httpx.Response(
            200,
            json={
                "code": "200",
                "now": {
                    "text": "多云",
                    "temp": "25",
                    "humidity": "62",
                    "windDir": "东北风",
                    "windScale": "2",
                    "obsTime": "2025-06-05T15:00+08:00",
                    "feelsLike": "27",
                    "precip": "0.0",
                    "pressure": "1002",
                    "vis": "24",
                    "cloud": "51",
                    "dew": "18",
                },
            },
        )

    monkeypatch.setattr("app.services.weather.make_client", _mock_transport(handler))

    data = client.get(f"{BASE}/now").json()["data"]
    assert data["degraded"] is False
    assert data["feels_like"] == 27.0
    assert data["precip"] == 0.0
    assert data["pressure"] == 1002.0
    assert data["vis"] == 24.0
    assert data["cloud"] == 51.0
    assert data["dew"] == 18.0
    assert data["obs_time"] == "2025-06-05T15:00+08:00"


def test_now_extended_fields_missing_are_none(client, fake_redis, monkeypatch) -> None:
    """和风缺字段 / 旧缓存结构 → 扩展字段为 None（向后兼容），不 500。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "200",
                "now": {"text": "晴", "temp": "22", "humidity": "40"},
            },
        )

    monkeypatch.setattr("app.services.weather.make_client", _mock_transport(handler))

    data = client.get(f"{BASE}/now").json()["data"]
    assert data["text"] == "晴"
    assert data["feels_like"] is None
    assert data["pressure"] is None
    assert data["vis"] is None
    assert data["cloud"] is None
    assert data["dew"] is None
    assert data["obs_time"] is None


def _daily_item(day: int) -> dict:
    """构造一条 daily 预报（供 7d mock 复用）。"""
    return {
        "fxDate": f"2025-06-{day:02d}",
        "tempMax": "30",
        "tempMin": "20",
        "textDay": "晴",
        "textNight": "多云",
        "humidity": "50",
        "precip": "0.0",
    }


def test_forecast_7d_and_cache_key_with_days(client, fake_redis, monkeypatch) -> None:
    """days=7 → 走 /v7/weather/7d 且返回 7 天；缓存键必须带天数。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")
    called_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_paths.append(request.url.path)
        if request.url.path.endswith("/v7/weather/7d"):
            return httpx.Response(200, json={"code": "200", "daily": [_daily_item(i) for i in range(1, 8)]})
        return httpx.Response(500, json={"code": "500"})

    monkeypatch.setattr("app.services.weather.make_client", _mock_transport(handler))

    resp = client.get(f"{BASE}/forecast?days=7")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["degraded"] is False
    assert len(data["list"]) == 7
    assert data["list"][6]["date"] == "2025-06-07"
    assert any(p.endswith("/v7/weather/7d") for p in called_paths)

    # 缓存键带天数（3 天与 7 天不共用键）
    assert f"weather:forecast:{settings.weather_location}:7" in fake_redis.store
    assert f"weather:forecast:{settings.weather_location}:3" not in fake_redis.store

    # 二次调用命中缓存，不再发外呼
    calls_after_first = len(called_paths)
    resp2 = client.get(f"{BASE}/forecast?days=7")
    assert resp2.json()["data"]["list"][0]["date"] == "2025-06-01"
    assert len(called_paths) == calls_after_first


def test_forecast_3d_still_uses_3d_path(client, fake_redis, monkeypatch) -> None:
    """days≤3 仍走 /v7/weather/3d（预警引擎 days=3 语义不变），缓存键 :3。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")
    called_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_paths.append(request.url.path)
        return httpx.Response(200, json={"code": "200", "daily": [_daily_item(1), _daily_item(2), _daily_item(3)]})

    monkeypatch.setattr("app.services.weather.make_client", _mock_transport(handler))

    data = client.get(f"{BASE}/forecast?days=3").json()["data"]
    assert data["degraded"] is False
    assert len(data["list"]) == 3
    assert any(p.endswith("/v7/weather/3d") for p in called_paths)
    assert not any(p.endswith("/v7/weather/7d") for p in called_paths)
    assert f"weather:forecast:{settings.weather_location}:3" in fake_redis.store


def _hourly_item(hour: int) -> dict:
    """构造一条 24h 逐时预报（供 mock 复用）。"""
    return {
        "fxTime": f"2025-06-05T{hour:02d}:00+08:00",
        "temp": str(20 + hour % 10),
        "text": "多云" if hour % 2 else "小雨",
        "icon": "101",
        "wind360": "45",
        "windDir": "东北风",
        "windScale": "1-2",
        "windSpeed": "8",
        "humidity": "65",
        "precip": "0.1",
        "pressure": "1005",
        "cloud": "40",
        "dew": "16",
        "pop": str(hour % 100),
    }


def test_hourly_success_and_cache(client, fake_redis, monkeypatch) -> None:
    """24h 逐时接口：24 条 + 字段映射正确 + 缓存命中不发二次外呼。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        assert request.url.path.endswith("/v7/weather/24h")
        return httpx.Response(200, json={"code": "200", "hourly": [_hourly_item(i) for i in range(24)]})

    monkeypatch.setattr("app.services.weather.make_client", _mock_transport(handler))

    resp = client.get(f"{BASE}/hourly")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["degraded"] is False
    assert len(data["list"]) == 24
    first = data["list"][0]
    assert first["fx_time"] == "2025-06-05T00:00+08:00"
    assert first["temp"] == 20.0
    assert first["text"] == "小雨"
    assert first["humidity"] == 65.0
    assert first["precip"] == 0.1
    assert first["pop"] == 0.0
    assert first["wind_dir"] == "东北风"
    assert first["wind_scale"] == "1-2"

    # 缓存键固定 + TTL 独立（键存在即可，TTL 值由 redis 侧保证）
    assert f"weather:hourly:{settings.weather_location}" in fake_redis.store

    # 二次调用命中缓存
    client.get(f"{BASE}/hourly")
    assert calls["count"] == 1


def test_hourly_degraded_on_error(client, fake_redis, monkeypatch) -> None:
    """24h 接口网络失败 → 仍 200、list=[]、degraded=true，不 500。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr("app.services.weather.make_client", _mock_transport(handler))

    resp = client.get(f"{BASE}/hourly")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["degraded"] is True
    assert data["list"] == []
