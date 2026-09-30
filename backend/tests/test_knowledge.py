# -*- coding: utf-8 -*-
"""知识库（knowledge）模块测试：门户（需登录）+ admin CRUD + 重新向量化 + 动态聚合。

对齐设计 §6 与 team-lead 裁决：门户读端点需要登录；作物分类动态聚合、不写死篇数。
kb 目录用 ``tmp_path`` 隔离，避免污染真实仓库。
"""
import pytest

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.services.knowledge_admin import knowledge_admin_service

PORTAL = "/api/v1/knowledge"
ADMIN = "/api/v1/admin/knowledge"


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


@pytest.fixture
def kb_dir(tmp_path, monkeypatch):
    """把 ``kb/diseases`` 指向临时目录，隔离文件写入。"""
    root = tmp_path / "diseases"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "kb_diseases_dir", str(root))
    return root


def test_portal_requires_login(client) -> None:
    """门户四端点未登录必须被拒（401 / 1003）。"""
    for path in (f"{PORTAL}/crops", f"{PORTAL}/docs", f"{PORTAL}/docs/1", f"{PORTAL}/search?q=番茄"):
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} 应拒绝未登录访问"
        assert resp.json()["code"] == 1003


def test_portal_crops_dynamic(client, db_session, make_user, kb_dir) -> None:
    """作物分类由 class-map 动态聚合，且随 knowledge_docs 计数变化（不写死篇数）。"""
    token, _ = make_user("alice")
    resp = client.get(f"{PORTAL}/crops", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert items, "class-map 应能聚合出作物分类"
    assert all("crop_cn" in it and "disease_count" in it for it in items)
    assert all(it["disease_count"] == 0 for it in items)  # 空库时计数为 0


def test_portal_docs_and_search(client, make_user, admin_token, kb_dir) -> None:
    """门户列表/详情/检索可用；检索降级为关键字模式（无向量索引时）。"""
    token, _ = make_user("alice")
    # 空库列表
    listed = client.get(f"{PORTAL}/docs", headers=_headers(token))
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 0

    # 详情不存在 → 404 / 7001
    missing = client.get(f"{PORTAL}/docs/999999", headers=_headers(token))
    assert missing.status_code == 404
    assert missing.json()["code"] == 7001

    # 新建两条文档
    for i in range(2):
        created = client.post(
            f"{ADMIN}/docs",
            json={
                "title": f"番茄晚疫病测试{i}",
                "crop": "番茄",
                "disease": "番茄晚疫病",
                "content_md": f"# 番茄晚疫病测试{i}\n\n## 症状\n叶片水渍状。",
                "slug": f"test-tomato-late-blight-{i}",
            },
            headers=_headers(admin_token),
        )
        assert created.status_code == 200, created.text

    listed2 = client.get(f"{PORTAL}/docs?q=番茄", headers=_headers(token))
    assert listed2.json()["data"]["total"] == 2

    detail = client.get(f"{PORTAL}/docs/{listed2.json()['data']['items'][0]['id']}", headers=_headers(token))
    assert detail.status_code == 200
    assert "content_md" in detail.json()["data"]

    search = client.get(f"{PORTAL}/search?q=番茄晚疫病", headers=_headers(token))
    assert search.status_code == 200
    assert search.json()["data"]["mode"] in {"semantic", "keyword"}


def test_admin_doc_crud_and_conflict(client, admin_token, kb_dir) -> None:
    """admin 增改查删全通；slug 冲突 → 409 / 7002。"""
    payload = {
        "title": "苹果黑星病",
        "crop": "苹果",
        "disease": "苹果黑星病",
        "content_md": "# 苹果黑星病\n\n## 症状\n叶片黑斑。",
        "slug": "apple-scab-admin",
    }
    created = client.post(f"{ADMIN}/docs", json=payload, headers=_headers(admin_token))
    assert created.status_code == 200, created.text
    doc_id = created.json()["data"]["id"]
    assert created.json()["data"]["vector_status"] == "pending"
    assert (kb_dir / "apple-scab-admin.md").exists()

    # 冲突
    conflict = client.post(f"{ADMIN}/docs", json=payload, headers=_headers(admin_token))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 7002

    # 更新
    updated = client.put(
        f"{ADMIN}/docs/{doc_id}",
        json={"content_md": "# 苹果黑星病\n\n## 症状\n更新后的正文。"},
        headers=_headers(admin_token),
    )
    assert updated.status_code == 200
    assert "更新后的正文" in updated.json()["data"]["content_md"]

    # 删除
    deleted = client.delete(f"{ADMIN}/docs/{doc_id}", headers=_headers(admin_token))
    assert deleted.status_code == 200
    assert client.delete(f"{ADMIN}/docs/{doc_id}", headers=_headers(admin_token)).status_code == 404


def test_admin_upload_md_file(client, admin_token, kb_dir) -> None:
    """multipart 上传 .md：以 H1 作标题。"""
    resp = client.post(
        f"{ADMIN}/docs",
        files={"file": ("tomato.md", "# 番茄晚疫病\n\n正文".encode("utf-8"), "text/markdown")},
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["title"] == "番茄晚疫病"


def test_admin_reindex(client, admin_token, monkeypatch) -> None:
    """触发重新向量化（桩掉子进程）→ accepted=true；状态端点结构正确。"""
    monkeypatch.setattr(knowledge_admin_service, "reindex_async", lambda: True)

    resp = client.post(f"{ADMIN}/reindex", headers=_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["accepted"] is True

    status = client.get(f"{ADMIN}/reindex/status", headers=_headers(admin_token))
    assert status.status_code == 200
    data = status.json()["data"]
    for key in ("running", "last_built_at", "count", "error"):
        assert key in data


def test_admin_knowledge_requires_admin(client, make_user) -> None:
    """普通用户访问知识管理端 → 403 / 1004。"""
    token, _ = make_user("alice")
    resp = client.get(f"{ADMIN}/docs", headers=_headers(token))
    assert resp.status_code == 403
    assert resp.json()["code"] == 1004
