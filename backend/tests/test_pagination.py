# -*- coding: utf-8 -*-
"""分页边界测试（设计 §6.3：page≥1、1≤page_size≤100、pages=ceil(total/page_size)）。"""
import math

import pytest

from tests.conftest import auth_headers

BASE = "/api/v1/detection"
TOTAL = 5


@pytest.fixture
def five_records(client, make_user, create_record):
    """建 1 个用户 + 5 条检测记录。"""
    token, _ = make_user("page_user")
    for i in range(TOTAL):
        create_record(token, label=f"Crop___disease_{i}")
    return token


def test_default_pagination(five_records, client) -> None:
    """默认 page=1 / page_size=10。"""
    data = client.get(f"{BASE}/records", headers=auth_headers(five_records)).json()["data"]
    assert data["total"] == TOTAL
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["pages"] == 1
    assert len(data["items"]) == TOTAL


def test_page_slices_are_disjoint_and_complete(five_records, client) -> None:
    """逐页翻取：各页不重不漏，并集恰为全部记录。"""
    token = five_records
    collected: list[int] = []
    page = 1
    while True:
        data = client.get(
            f"{BASE}/records?page={page}&page_size=2", headers=auth_headers(token)
        ).json()["data"]
        assert data["pages"] == math.ceil(TOTAL / 2) == 3
        if not data["items"]:
            break
        collected.extend(item["id"] for item in data["items"])
        page += 1

    assert len(collected) == TOTAL
    assert len(set(collected)) == TOTAL  # 无重复
    # 与一次性取全部一致
    all_ids = [
        item["id"]
        for item in client.get(
            f"{BASE}/records?page=1&page_size=100", headers=auth_headers(token)
        ).json()["data"]["items"]
    ]
    assert sorted(collected) == sorted(all_ids)


def test_page_beyond_total_returns_empty(five_records, client) -> None:
    """page 超出总数 → items 为空但 total/pages 仍正确。"""
    data = client.get(
        f"{BASE}/records?page=99&page_size=2", headers=auth_headers(five_records)
    ).json()["data"]
    assert data["items"] == []
    assert data["total"] == TOTAL
    assert data["pages"] == 3
    assert data["page"] == 99


def test_last_page_partial(five_records, client) -> None:
    """末页条目数正确（5 条 / 每页 2 → 第 3 页 1 条）。"""
    data = client.get(
        f"{BASE}/records?page=3&page_size=2", headers=auth_headers(five_records)
    ).json()["data"]
    assert len(data["items"]) == 1


@pytest.mark.parametrize("page", [0, -1, -100])
def test_invalid_page_rejected(five_records, client, page) -> None:
    """page < 1 → 422（信封齐全）。"""
    resp = client.get(f"{BASE}/records?page={page}", headers=auth_headers(five_records))
    assert resp.status_code == 422
    assert set(resp.json().keys()) == {"code", "message", "data"}


@pytest.mark.parametrize("page_size", [0, -1, 101, 1000])
def test_invalid_page_size_rejected(five_records, client, page_size) -> None:
    """page_size 越界 → 422。"""
    resp = client.get(f"{BASE}/records?page_size={page_size}", headers=auth_headers(five_records))
    assert resp.status_code == 422


@pytest.mark.parametrize("page_size", [1, 100])
def test_page_size_bounds_accepted(five_records, client, page_size) -> None:
    """page_size 边界 1 / 100 合法。"""
    resp = client.get(f"{BASE}/records?page_size={page_size}", headers=auth_headers(five_records))
    assert resp.status_code == 200
    assert resp.json()["data"]["page_size"] == page_size
