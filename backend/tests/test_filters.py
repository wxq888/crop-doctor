# -*- coding: utf-8 -*-
"""记录列表筛选测试：病害 / 严重度 / 作物 / 时间范围（设计 §5.1 query 参数）。

筛选条件必须与 ``user_id`` 过滤叠加（不得成为越权侧信道）。
"""
import pytest

from tests.conftest import auth_headers

BASE = "/api/v1/detection"


def _total(client, token, query: str = "") -> int:
    url = f"{BASE}/records?page_size=100{('&' + query) if query else ''}"
    body = client.get(url, headers=auth_headers(token)).json()
    assert body["code"] == 0
    return body["data"]["total"]


@pytest.fixture
def dataset(client, make_user, create_record):
    """构造 3 条差异化记录：不同病害 / 严重度 / 作物。"""
    token, _ = make_user("filter_user")
    # 轻微：1 框、面积 0
    r1 = create_record(token, spot_count=1, area_ratio=0.0, label="Apple___Apple_scab")
    # 中等：5 框、面积 0
    r2 = create_record(token, spot_count=5, area_ratio=0.0, label="Tomato___Late_blight")
    # 严重：1 框、面积 0.2
    r3 = create_record(token, spot_count=1, area_ratio=0.2, label="Apple___Black_rot")
    return token, {"minor": r1, "moderate": r2, "severe": r3}


def test_no_filter_returns_all(dataset, client) -> None:
    """无筛选 → 全部 3 条。"""
    token, _ = dataset
    assert _total(client, token) == 3


def test_filter_by_disease(dataset, client) -> None:
    """按病害精确筛选。"""
    token, _ = dataset
    assert _total(client, token, "disease=Apple___Apple_scab") == 1
    assert _total(client, token, "disease=Tomato___Late_blight") == 1
    assert _total(client, token, "disease=No___Such_Disease") == 0


def test_filter_by_severity_level(dataset, client) -> None:
    """按严重度筛选：1/2/3 各命中自身。"""
    token, recs = dataset
    assert recs["minor"]["severity_level"] == 1
    assert recs["moderate"]["severity_level"] == 2
    assert recs["severe"]["severity_level"] == 3

    assert _total(client, token, "severity_level=1") == 1
    assert _total(client, token, "severity_level=2") == 1
    assert _total(client, token, "severity_level=3") == 1
    assert _total(client, token, "severity_level=0") == 0


def test_filter_by_crop(dataset, client) -> None:
    """按作物（top_disease 前缀派生）筛选。"""
    token, _ = dataset
    assert _total(client, token, "crop=Apple") == 2
    assert _total(client, token, "crop=Tomato") == 1
    assert _total(client, token, "crop=Banana") == 0


def test_filter_combined(dataset, client) -> None:
    """多条件叠加（病害 + 作物）等价于交集。"""
    token, _ = dataset
    assert _total(client, token, "crop=Apple&disease=Apple___Black_rot") == 1
    assert _total(client, token, "crop=Tomato&disease=Apple___Black_rot") == 0


def test_filter_by_time_range(dataset, client) -> None:
    """时间范围筛选：宽松区间命中全部，未来/过去区间命中 0。"""
    token, _ = dataset
    assert _total(client, token, "start=2000-01-01T00:00:00") == 3
    assert _total(client, token, "end=2000-01-01T00:00:00") == 0
    assert _total(client, token, "start=2999-01-01T00:00:00") == 0
