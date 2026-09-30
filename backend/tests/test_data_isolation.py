# -*- coding: utf-8 -*-
"""数据隔离红线专项测试（架构 §6.9 / 实现级设计 §6.12，本项目最重要的安全约束）。

真实构建用户 A / 用户 B，各自造数据，交叉访问 **列表 / 详情 / 删除 / Grad-CAM**
四个入口，验证：
- A 的列表只含 A 的记录，B 的列表只含 B 的记录（数量与 id 均严格隔离）；
- 交叉取详情 / 热力图 / 删除 一律 404 / 2004，且不产生副作用（B 的记录安然无恙）；
- 筛选参数无法成为越权探测的侧信道（按对方的病害筛选仍查不到）；
- 不存在的 id 也返回 2004（不区分"不存在"与"无权"，防探测）。
"""
import pytest

from tests.conftest import auth_headers

BASE = "/api/v1/detection"


def _list_ids(client, token) -> list[int]:
    """取当前用户列表页全部 id（单页足够，本测试数据量小）。"""
    body = client.get(f"{BASE}/records?page=1&page_size=100", headers=auth_headers(token)).json()
    assert body["code"] == 0
    return [item["id"] for item in body["data"]["items"]]


def _assert_2004(resp) -> None:
    """断言 404 / 2004 且信封完整。"""
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["code"] == 2004
    assert set(body.keys()) == {"code", "message", "data"}


@pytest.fixture
def two_users_with_records(client, make_user, create_record):
    """用户 A 建 2 条记录、用户 B 建 1 条记录，返回 (tokenA, tokenB, recA_ids, recB_id)。"""
    token_a, _ = make_user("iso_alice")
    token_b, _ = make_user("iso_bob")

    rec_a1 = create_record(token_a, label="Apple___Apple_scab", location="北京")
    rec_a2 = create_record(token_a, label="Apple___Black_rot", location="上海")
    rec_b1 = create_record(token_b, label="Tomato___Late_blight")

    return token_a, token_b, [rec_a1["id"], rec_a2["id"]], rec_b1["id"]


def test_list_is_strictly_isolated(two_users_with_records, client) -> None:
    """A/B 的列表严格隔离：数量和 id 集合均只含本人记录。"""
    token_a, token_b, ids_a, id_b = two_users_with_records

    data_a = client.get(f"{BASE}/records", headers=auth_headers(token_a)).json()["data"]
    assert data_a["total"] == 2
    assert sorted(item["id"] for item in data_a["items"]) == sorted(ids_a)

    data_b = client.get(f"{BASE}/records", headers=auth_headers(token_b)).json()["data"]
    assert data_b["total"] == 1
    assert [item["id"] for item in data_b["items"]] == [id_b]

    # A 的列表里绝不含 B 的记录 id
    assert id_b not in _list_ids(client, token_a)


def test_cross_user_detail_forbidden(two_users_with_records, client) -> None:
    """B 取 A 的详情 / A 取 B 的详情 → 404 / 2004。"""
    token_a, token_b, ids_a, id_b = two_users_with_records

    _assert_2004(client.get(f"{BASE}/records/{ids_a[0]}", headers=auth_headers(token_b)))
    _assert_2004(client.get(f"{BASE}/records/{id_b}", headers=auth_headers(token_a)))


def test_cross_user_gradcam_forbidden(two_users_with_records, client) -> None:
    """跨用户取 Grad-CAM 状态 → 404 / 2004。"""
    token_a, token_b, ids_a, id_b = two_users_with_records

    _assert_2004(client.get(f"{BASE}/records/{ids_a[1]}/gradcam", headers=auth_headers(token_b)))
    _assert_2004(client.get(f"{BASE}/records/{id_b}/gradcam", headers=auth_headers(token_a)))


def test_cross_user_delete_forbidden_and_no_side_effect(two_users_with_records, client) -> None:
    """B 删 A 的记录 → 404 / 2004，且 A 的记录与 B 自己的记录均不受影响。"""
    token_a, token_b, ids_a, id_b = two_users_with_records

    for rid in ids_a:
        _assert_2004(client.delete(f"{BASE}/records/{rid}", headers=auth_headers(token_b)))

    # A 的记录仍在
    assert sorted(_list_ids(client, token_a)) == sorted(ids_a)
    # B 的记录仍在
    assert _list_ids(client, token_b) == [id_b]
    # A 仍可取自己详情
    assert client.get(f"{BASE}/records/{ids_a[0]}", headers=auth_headers(token_a)).status_code == 200


def test_filter_cannot_leak_other_users_data(two_users_with_records, client) -> None:
    """按"对方独有病害"筛选，仍查不到对方数据（无侧信道）。"""
    token_a, token_b, _ids_a, id_b = two_users_with_records

    # B 独有病害：A 用它筛选应为空
    leak = client.get(
        f"{BASE}/records?disease=Tomato___Late_blight", headers=auth_headers(token_a)
    ).json()["data"]
    assert leak["total"] == 0
    assert leak["items"] == []
    assert id_b not in _list_ids(client, token_a)

    # 反向：B 用 A 独有病害筛选亦为空
    leak_b = client.get(
        f"{BASE}/records?disease=Apple___Apple_scab", headers=auth_headers(token_b)
    ).json()["data"]
    assert leak_b["total"] == 0


def test_nonexistent_record_returns_2004(client, make_user) -> None:
    """不存在的 id → 404 / 2004（与越权同码，防探测）。"""
    token, _ = make_user("iso_carol")
    _assert_2004(client.get(f"{BASE}/records/99999999", headers=auth_headers(token)))
    _assert_2004(client.get(f"{BASE}/records/99999999/gradcam", headers=auth_headers(token)))
    _assert_2004(client.delete(f"{BASE}/records/99999999", headers=auth_headers(token)))


def test_delete_own_record_removes_details(two_users_with_records, client, db_session) -> None:
    """本人删除记录后，明细行随之级联删除（外键 ON DELETE CASCADE）。"""
    token_a, _token_b, ids_a, _id_b = two_users_with_records
    from sqlalchemy import func, select

    from app.models.detection import DetectionDetail

    detail_count_before = db_session.scalar(
        select(func.count()).select_from(DetectionDetail).where(DetectionDetail.record_id == ids_a[0])
    )
    assert detail_count_before == 1

    resp = client.delete(f"{BASE}/records/{ids_a[0]}", headers=auth_headers(token_a))
    assert resp.status_code == 200

    detail_count_after = db_session.scalar(
        select(func.count()).select_from(DetectionDetail).where(DetectionDetail.record_id == ids_a[0])
    )
    assert detail_count_after == 0
