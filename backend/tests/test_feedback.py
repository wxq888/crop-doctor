# -*- coding: utf-8 -*-
"""反馈工单（feedback）模块测试：状态机闭环 / 未读 / 多轮 / 数据隔离 / 鉴权。

对齐设计 §5：``pending → replied → closed``；``closed`` 为终态；越权统一 404 / 6001。
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.user import User

H5 = "/api/v1/feedback"
ADMIN = "/api/v1/admin/feedback"


def _headers(token: str) -> dict:
    """构造 Bearer 头。"""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(db_session) -> str:
    """创建管理员并签发 token。"""
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


def _create_question(client, token: str, title: str = "叶片发黄怎么办") -> dict:
    """创建一条 question 工单。"""
    resp = client.post(
        f"{H5}",
        json={"type": "question", "title": title, "content": "我的番茄叶子发黄了，怎么办？"},
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_ticket_state_machine_closed_loop(client, make_user, admin_token) -> None:
    """创建 → 管理员回复 → 用户未读 → 用户读取 → 未读清零 → 追问 → 关闭 → 终态拒绝。"""
    token, _ = make_user("alice")
    fb = _create_question(client, token)
    fb_id = fb["id"]
    assert fb["status"] == "pending"
    assert fb["message_count"] == 1

    # 管理员回复 → replied
    reply = client.post(
        f"{ADMIN}/{fb_id}/reply",
        json={"content": "可能是缺镁，建议补充含镁叶面肥。"},
        headers=_headers(admin_token),
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["data"]["sender_role"] == "admin"

    detail = client.get(f"{ADMIN}/{fb_id}", headers=_headers(admin_token))
    assert detail.json()["data"]["status"] == "replied"

    # 用户未读 = 1（管理员消息）
    user_unread = client.get(f"{H5}/unread-count", headers=_headers(token))
    assert user_unread.json()["data"]["count"] == 1

    # 用户打开详情 → 自动置已读
    got = client.get(f"{H5}/{fb_id}", headers=_headers(token))
    assert got.status_code == 200
    assert len(got.json()["data"]["messages"]) == 2

    user_unread2 = client.get(f"{H5}/unread-count", headers=_headers(token))
    assert user_unread2.json()["data"]["count"] == 0

    # 用户追问 → 复位 pending，且对管理员产生未读
    follow = client.post(f"{H5}/{fb_id}/messages", json={"content": "补镁用哪种肥料？"}, headers=_headers(token))
    assert follow.status_code == 200
    assert follow.json()["data"]["sender_role"] == "user"

    my = client.get(f"{H5}/mine", headers=_headers(token))
    assert my.json()["data"]["items"][0]["status"] == "pending"

    admin_unread = client.get(f"{ADMIN}/unread-count", headers=_headers(admin_token))
    assert admin_unread.json()["data"]["count"] >= 1

    # 管理员关闭 → closed（终态）
    closed = client.post(f"{ADMIN}/{fb_id}/close", headers=_headers(admin_token))
    assert closed.status_code == 200
    assert closed.json()["data"]["status"] == "closed"

    # 终态：用户追问 / 管理员回复均 409 / 6002
    after_user = client.post(f"{H5}/{fb_id}/messages", json={"content": "还在吗"}, headers=_headers(token))
    assert after_user.status_code == 409
    assert after_user.json()["code"] == 6002

    after_admin = client.post(
        f"{ADMIN}/{fb_id}/reply", json={"content": "已关闭"}, headers=_headers(admin_token)
    )
    assert after_admin.status_code == 409
    assert after_admin.json()["code"] == 6002

    # 重复关闭 → 409 / 6003（非法流转）
    again = client.post(f"{ADMIN}/{fb_id}/close", headers=_headers(admin_token))
    assert again.status_code == 409
    assert again.json()["code"] == 6003


def test_ticket_isolation_between_users(client, make_user) -> None:
    """用户 A 看不到 B 的工单；越权取详情 404 / 6001。"""
    token_a, _ = make_user("alice")
    token_b, _ = make_user("bob")
    fb = _create_question(client, token_a, title="A 的工单")
    fb_id = fb["id"]

    # B 的列表为空
    mine_b = client.get(f"{H5}/mine", headers=_headers(token_b))
    assert mine_b.json()["data"]["total"] == 0

    # B 越权取 A 的工单 → 404 / 6001
    got = client.get(f"{H5}/{fb_id}", headers=_headers(token_b))
    assert got.status_code == 404
    assert got.json()["code"] == 6001

    # B 追问 A 的工单 → 404 / 6001
    follow = client.post(f"{H5}/{fb_id}/messages", json={"content": "hi"}, headers=_headers(token_b))
    assert follow.status_code == 404
    assert follow.json()["code"] == 6001


def test_result_verdict_record_ownership(client, make_user, create_record) -> None:
    """result_verdict 关联他人在检测记录 → 404 / 2004。"""
    token_a, _ = make_user("alice")
    token_b, _ = make_user("bob")
    record = create_record(token_a)
    record_id = record["id"]

    ok_resp = client.post(
        f"{H5}",
        json={
            "type": "result_verdict",
            "title": "识别错了",
            "content": "这不是晚疫病",
            "record_id": record_id,
            "verdict": "wrong",
            "correct_disease": "番茄早疫病",
        },
        headers=_headers(token_a),
    )
    assert ok_resp.status_code == 200, ok_resp.text
    assert ok_resp.json()["data"]["record_id"] == record_id

    # B 关联 A 的记录 → 404 / 2004
    bad = client.post(
        f"{H5}",
        json={"type": "result_verdict", "title": "x", "content": "y", "record_id": record_id},
        headers=_headers(token_b),
    )
    assert bad.status_code == 404
    assert bad.json()["code"] == 2004


def test_admin_feedback_requires_admin(client, make_user, admin_token) -> None:
    """普通用户访问管理端工单 → 403 / 1004；管理员可见全量。"""
    token, _ = make_user("alice")
    _create_question(client, token)

    forbidden = client.get(ADMIN, headers=_headers(token))
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 1004

    allowed = client.get(f"{ADMIN}?unread_only=true", headers=_headers(admin_token))
    assert allowed.status_code == 200
    assert allowed.json()["data"]["total"] >= 1


def test_missing_ticket_404(client, make_user) -> None:
    """不存在的工单 → 404 / 6001。"""
    token, _ = make_user("alice")
    resp = client.get(f"{H5}/999999", headers=_headers(token))
    assert resp.status_code == 404
    assert resp.json()["code"] == 6001
