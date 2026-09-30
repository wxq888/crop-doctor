# -*- coding: utf-8 -*-
"""预警（warning）模块测试：风险匹配 / 降级零写入 / 规则 CRUD / H5 查询 / 鉴权。

重点：``WEATHER_API_KEY`` 为空时三个相关路径 200 + ``degraded=true``，且
``alert_records`` **零新增**、服务不 500（对齐设计 §4.2 红线）。
"""
import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.models.warning import AlertRecord, DiseaseWeatherRule
from app.services.weather import DailyForecast
from app.services.weather_risk import RISK_CN, start_scheduler, weather_risk_engine

BASE = "/api/v1/warning"


def _headers(token: str) -> dict:
    """构造 Bearer 头。"""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(db_session) -> str:
    """在测试库中创建一个管理员并签发 token。"""
    admin = User(
        username="root",
        password_hash=hash_password("secret123"),
        nickname="管理员",
        role="admin",
        status=1,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    token, _ = create_access_token(admin.id, admin.role)
    return token


def _count_alerts(db) -> int:
    """当前 ``alert_records`` 行数。"""
    return int(db.scalar(select(func.count()).select_from(AlertRecord)) or 0)


def _create_rule(client, token: str, **overrides) -> dict:
    """经 API 新建一条规则。"""
    payload = {
        "disease": "Tomato___Late_blight",
        "crop": "Tomato",
        "temp_min": 10.0,
        "temp_max": 30.0,
        "humidity_min": 80.0,
        "rain_condition": "rain",
        "risk_level": "high",
        "advice": "注意排水、及时用药",
        "enabled": 1,
    }
    payload.update(overrides)
    resp = client.post(f"{BASE}/rules", json=payload, headers=_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ============================================================
# 纯函数：规则匹配
# ============================================================
def _rule(**kw) -> DiseaseWeatherRule:
    """构造未入库的规则对象（纯匹配测试用）。"""
    rule = DiseaseWeatherRule(
        disease=kw.get("disease", "Tomato___Late_blight"),
        crop=kw.get("crop", "Tomato"),
        temp_min=kw.get("temp_min", 10.0),
        temp_max=kw.get("temp_max", 30.0),
        humidity_min=kw.get("humidity_min"),
        humidity_max=kw.get("humidity_max"),
        rain_condition=kw.get("rain_condition", "any"),
        risk_level=kw.get("risk_level", "high"),
        advice=kw.get("advice", None),
        enabled=1,
    )
    rule.id = kw.get("id", 1)
    return rule


def _day(**kw) -> DailyForecast:
    """构造单日预报。"""
    return DailyForecast(
        date=kw.get("date", "2026-09-18"),
        temp_max=kw.get("temp_max", 25.0),
        temp_min=kw.get("temp_min", 15.0),
        text_day=kw.get("text_day", "晴"),
        text_night=kw.get("text_night", "晴"),
        humidity=kw.get("humidity", None),
        precip=kw.get("precip", None),
    )


def test_match_rule_temperature_intersection() -> None:
    """温度区间求交：无交集不命中，有交集命中。"""
    rule = _rule(temp_min=10.0, temp_max=20.0)
    assert weather_risk_engine.match_rule(rule, _day(temp_min=25, temp_max=30)) is None
    hit = weather_risk_engine.match_rule(rule, _day(temp_min=15, temp_max=28))
    assert hit is not None
    assert hit.matched["temp"] is True


def test_match_rule_humidity_missing_is_ignored() -> None:
    """湿度有约束但当日缺数据 → 忽略该约束（不判否，避免漏报）。"""
    rule = _rule(humidity_min=80.0, humidity_max=100.0)
    hit = weather_risk_engine.match_rule(rule, _day(humidity=None))
    assert hit is not None
    assert hit.matched["humidity"] is False


def test_match_rule_rain_condition() -> None:
    """rain → 仅雨天命中；no_rain → 仅非雨天命中。"""
    rain_rule = _rule(rain_condition="rain")
    assert weather_risk_engine.match_rule(rain_rule, _day(text_day="晴", precip=0)) is None
    assert weather_risk_engine.match_rule(rain_rule, _day(text_day="中雨", precip=5)) is not None

    dry_rule = _rule(rain_condition="no_rain")
    assert weather_risk_engine.match_rule(dry_rule, _day(text_day="中雨", precip=5)) is None
    assert weather_risk_engine.match_rule(dry_rule, _day(text_day="晴", precip=0)) is not None


def test_risk_cn_mapping() -> None:
    """风险等级中文映射齐全。"""
    assert RISK_CN == {"high": "高", "mid": "中", "low": "低"}


# ============================================================
# 降级：零写入、绝不 500
# ============================================================
def test_degraded_refresh_and_overview_zero_write(client, db_session, admin_token, monkeypatch) -> None:
    """WEATHER_API_KEY 为空 → refresh/overview 200 + degraded=true + 零写库，且不发外部请求。"""
    monkeypatch.setattr(settings, "weather_api_key", "")

    def _boom() -> httpx.AsyncClient:  # 若被调用说明错误地发起了外部请求
        raise AssertionError("WEATHER_API_KEY 为空时不应发起外部请求")

    monkeypatch.setattr("app.services.weather.make_client", _boom)

    _create_rule(client, admin_token)  # 至少一条启用规则，才能走到天气分支
    before = _count_alerts(db_session)

    refresh = client.post(f"{BASE}/refresh", json={}, headers=_headers(admin_token))
    assert refresh.status_code == 200, refresh.text
    body = refresh.json()
    assert body["code"] == 0
    assert body["data"]["degraded"] is True
    assert body["data"]["created"] == 0

    overview = client.get(f"{BASE}/overview", headers=_headers(admin_token))
    assert overview.status_code == 200, overview.text
    assert overview.json()["data"]["degraded"] is True
    assert overview.json()["data"]["now"] is None
    assert overview.json()["data"]["forecast"] == []

    after = _count_alerts(db_session)
    assert after == before, f"降级时不应写库：{before} -> {after}"


def test_refresh_writes_when_forecast_available(client, db_session, admin_token, monkeypatch) -> None:
    """有预报时命中规则并写入 alert_records。"""
    monkeypatch.setattr(settings, "weather_api_key", "test-key")

    forecast = [
        DailyForecast(
            date="2026-09-18",
            temp_max=28.0,
            temp_min=18.0,
            text_day="中雨",
            text_night="小雨",
            humidity=90.0,
            precip=8.0,
        )
    ]

    async def fake_forecast(location=None, days=3):  # noqa: ANN001
        return forecast

    monkeypatch.setattr(
        "app.services.weather_risk.weather_service.get_forecast", fake_forecast
    )

    _create_rule(client, admin_token, humidity_min=80.0, rain_condition="rain")
    before = _count_alerts(db_session)
    resp = client.post(f"{BASE}/refresh", json={}, headers=_headers(admin_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["degraded"] is False
    assert data["created"] >= 1
    assert _count_alerts(db_session) > before

    # 幂等：再次刷新不应重复写库（去重）
    mid = _count_alerts(db_session)
    client.post(f"{BASE}/refresh", json={}, headers=_headers(admin_token))
    assert _count_alerts(db_session) == mid


# ============================================================
# 规则 CRUD + 鉴权
# ============================================================
def test_rules_crud(client, admin_token) -> None:
    """规则增改查删全通；更新不存在 → 404 / 5002。"""
    created = _create_rule(client, admin_token, disease="Apple___Apple_scab", risk_level="mid")
    rule_id = created["id"]
    assert created["disease_cn"] == "苹果黑星病"  # 中文名由后端派生

    listed = client.get(f"{BASE}/rules", headers=_headers(admin_token))
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] >= 1

    updated = client.put(
        f"{BASE}/rules/{rule_id}",
        json={"risk_level": "low", "enabled": 0},
        headers=_headers(admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["risk_level"] == "low"
    assert updated.json()["data"]["enabled"] == 0

    missing = client.put(
        f"{BASE}/rules/99999", json={"risk_level": "low"}, headers=_headers(admin_token)
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == 5002

    deleted = client.delete(f"{BASE}/rules/{rule_id}", headers=_headers(admin_token))
    assert deleted.status_code == 200
    assert client.delete(f"{BASE}/rules/{rule_id}", headers=_headers(admin_token)).status_code == 404


def test_non_admin_forbidden(client, make_user, admin_token) -> None:
    """普通用户访问管理端点 → 403 / 1004。"""
    token, _ = make_user("normal1")
    resp = client.get(f"{BASE}/rules", headers=_headers(token))
    assert resp.status_code == 403
    assert resp.json()["code"] == 1004


# ============================================================
# H5 查询 / 已读
# ============================================================
def test_h5_alerts_visibility_and_read(client, db_session, make_user, admin_token) -> None:
    """H5 可见全局预警；标记已读后未读数清零。"""
    token, user = make_user("alice")
    # 直接落一条全局预警
    alert = AlertRecord(
        source="weather",
        disease="Tomato___Late_blight",
        risk_level="high",
        content="番茄晚疫病 在未来 2026-09-18 有高爆发风险。",
        user_id=None,
        location="101010100",
        is_read=0,
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)

    listed = client.get(f"{BASE}/alerts", headers=_headers(token))
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert any(i["id"] == alert.id and i["for_me"] is True for i in items)

    unread = client.get(f"{BASE}/alerts/unread-count", headers=_headers(token))
    assert unread.json()["data"]["count"] >= 1

    read = client.post(f"{BASE}/alerts/{alert.id}/read", headers=_headers(token))
    assert read.status_code == 200

    unread2 = client.get(f"{BASE}/alerts/unread-count", headers=_headers(token))
    assert unread2.json()["data"]["count"] == 0

    # 不存在的预警 → 404 / 5001
    missing = client.post(f"{BASE}/alerts/999999/read", headers=_headers(token))
    assert missing.status_code == 404
    assert missing.json()["code"] == 5001


def test_alerts_require_login(client) -> None:
    """未登录访问 H5 预警 → 401 / 1003。"""
    resp = client.get(f"{BASE}/alerts")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


# ============================================================
# 定时器
# ============================================================
def test_start_scheduler_disabled(monkeypatch) -> None:
    """WARNING_ENABLED=false → start_scheduler 返回 None（不启线程）。"""
    monkeypatch.setattr(settings, "warning_enabled", False)
    assert start_scheduler() is None
