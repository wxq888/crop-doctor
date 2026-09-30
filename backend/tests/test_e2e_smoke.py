# -*- coding: utf-8 -*-
"""真实端到端冒烟测试（默认跳过）。

需先启动后端并设置环境变量：::

    CROPDOCTOR_E2E_BASE=http://127.0.0.1:8010 pytest tests/test_e2e_smoke.py -s

覆盖：注册 → 登录 → 真实叶片图上传检测 → 查记录 → 查详情 → 轮询 Grad-CAM →
确认热力图文件真实落盘；并验证"并发两个检测请求时 /health 仍秒回"。

注意：本测试会真实调用 YOLO / ResNet50 推理（CPU 数百 ms~数秒），并真实写盘。
"""
import concurrent.futures
import os
import time
from pathlib import Path

import httpx
import pytest

from app.core.config import REPO_ROOT, settings

BASE = os.environ.get("CROPDOCTOR_E2E_BASE", "").rstrip("/")
IMAGE_DIR = REPO_ROOT / "ml" / "data" / "raw" / "plantvillage" / "Apple___Apple_scab"

pytestmark = pytest.mark.skipif(
    not BASE, reason="E2E：需设置 CROPDOCTOR_E2E_BASE 指向运行中的后端"
)

AUTH = "/api/v1/auth"
DET = "/api/v1/detection"


def _pick_image() -> Path:
    """确定性地挑一张真实叶片图。"""
    files = sorted(p for p in IMAGE_DIR.iterdir() if p.suffix.upper() in {".JPG", ".JPEG", ".PNG"})
    assert files, f"未找到叶片图：{IMAGE_DIR}"
    return files[0]


def _abs_from_url(url: str) -> Path:
    """`/static/<rel>` → 上传目录绝对路径。"""
    assert url and url.startswith("/static/"), f"非法静态 URL：{url}"
    return settings.upload_path / url[len("/static/"):]


def _upload(client: httpx.Client, headers: dict, image: Path) -> httpx.Response:
    with image.open("rb") as fh:
        return client.post(
            f"{DET}/image",
            headers=headers,
            files={"file": (image.name, fh, "image/jpeg")},
            data={"location": "北京"},
        )


@pytest.fixture(scope="module")
def session_ctx():
    """模块级会话：注册 + 登录一个临时用户，退出时清理其检测记录。"""
    image = _pick_image()
    username = f"qa_smoke_{int(time.time())}"
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(180.0)) as client:
        reg = client.post(f"{AUTH}/register", json={"username": username, "password": "qaSmoke123"})
        assert reg.status_code == 200 and reg.json()["code"] == 0, reg.text
        print(f"\n[注册] {reg.status_code} {reg.json()}")

        login = client.post(f"{AUTH}/login", json={"username": username, "password": "qaSmoke123"})
        assert login.status_code == 200 and login.json()["code"] == 0, login.text
        token = login.json()["data"]["access_token"]
        print(f"[登录] {login.status_code} expires_in={login.json()['data']['expires_in']}s")

        ctx = {
            "client": client,
            "headers": {"Authorization": f"Bearer {token}"},
            "username": username,
            "image": image,
            "record_ids": [],
        }
        yield ctx

        # 清理：尽力删除本用户产生的记录。
        # 注：本机沙箱对"单轮累计删除 > 50 个文件"会强制中断进程，DELETE 端点的
        # 落盘清理可能因此被杀；此处 best-effort，清理失败不影响测试结论
        # （数据落在独立 QA 库，跑完整体丢弃）。
        try:
            for rid in ctx["record_ids"]:
                client.delete(f"{DET}/records/{rid}", headers=ctx["headers"])
            print(f"[清理] 已删除记录 {ctx['record_ids']}")
        except Exception as exc:  # noqa: BLE001
            print(f"[清理] 跳过（{exc!r}）")


def test_health_ok(session_ctx) -> None:
    """/health 返回 code=0，且 YOLO 已加载、Redis 连通。"""
    resp = session_ctx["client"].get("/health")
    assert resp.status_code == 200
    body = resp.json()
    print(f"\n[健康检查] {body}")
    assert body["code"] == 0
    assert body["data"]["yolo_loaded"] is True, "YOLO 未在启动时加载"
    assert body["data"]["redis"] is True, "Redis 未连通"


def test_real_detection_full_flow(session_ctx) -> None:
    """真实叶片图：上传 → 记录 → 详情 → Grad-CAM 落盘。"""
    client, headers, image = session_ctx["client"], session_ctx["headers"], session_ctx["image"]
    print(f"\n[图片] {image}")

    # 1) 上传检测
    resp = _upload(client, headers, image)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    print(f"[检测响应] {body}")
    session_ctx["record_ids"].append(data["id"])

    assert data["top_disease"], "未识别出病害"
    assert data["severity_level"] in (0, 1, 2, 3)
    assert data["severity_label"] in ("无", "轻微", "中等", "严重")
    assert data["spot_count"] >= 1
    assert data["gradcam_status"] in ("pending", "done")
    assert data["image_url"].startswith("/static/images/")
    assert data["annotated_url"].startswith("/static/annotated/")
    assert len(data["details"]) == data["spot_count"]
    assert data["created_at"].endswith("Z"), "时间未按 ISO-8601 带 Z 序列化"

    # 原图 / 标注图真实落盘
    assert _abs_from_url(data["image_url"]).is_file(), "原图未落盘"
    assert _abs_from_url(data["annotated_url"]).is_file(), "标注图未落盘"

    rid = data["id"]

    # 2) 记录列表
    listing = client.get(f"{DET}/records", headers=headers).json()
    print(f"[记录列表] total={listing['data']['total']} items={len(listing['data']['items'])}")
    assert listing["code"] == 0
    assert listing["data"]["total"] >= 1
    assert any(item["id"] == rid for item in listing["data"]["items"])

    # 3) 详情
    detail = client.get(f"{DET}/records/{rid}", headers=headers).json()["data"]
    print(f"[详情] crop={detail['crop']} location={detail['location']} "
          f"gradcam_status={detail['gradcam_status']}")
    assert detail["crop"] == "Apple"
    assert detail["location"] == "北京"

    # 4) 轮询 Grad-CAM 直到终态
    deadline = time.time() + 180
    status = None
    while time.time() < deadline:
        g = client.get(f"{DET}/records/{rid}/gradcam", headers=headers).json()["data"]
        status = g["status"]
        if status in ("done", "failed", "skipped"):
            break
        time.sleep(2)
    print(f"[Grad-CAM] 终态 status={status}")
    assert status == "done", f"Grad-CAM 未成功生成，status={status}"

    g = client.get(f"{DET}/records/{rid}/gradcam", headers=headers).json()["data"]
    assert g["url"] and g["url"].startswith("/static/gradcam/")
    cam_file = _abs_from_url(g["url"])
    assert cam_file.is_file(), f"热力图未落盘：{cam_file}"
    print(f"[热力图] {g['url']} 实际文件 {cam_file} size={cam_file.stat().st_size}B")

    # 5) 详情中的 gradcam_url 也应回填
    detail2 = client.get(f"{DET}/records/{rid}", headers=headers).json()["data"]
    assert detail2["gradcam_status"] == "done"
    assert detail2["gradcam_url"] == g["url"]


def test_concurrent_detection_does_not_block_health(session_ctx) -> None:
    """并发两个检测请求时，/health 仍应秒回（证明 CPU 推理未阻塞事件循环）。"""
    client, headers, image = session_ctx["client"], session_ctx["headers"], session_ctx["image"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_upload, client, headers, image) for _ in range(2)]
        time.sleep(0.2)  # 让两个检测请求先进入推理

        t0 = time.perf_counter()
        health = client.get("/health")
        health_ms = (time.perf_counter() - t0) * 1000

        results = []
        for fut in futures:
            r = fut.result(timeout=300)
            results.append(r)
            assert r.status_code == 200, r.text
            session_ctx["record_ids"].append(r.json()["data"]["id"])

    print(f"\n[并发] /health 在 2 个检测推理进行中耗时 {health_ms:.0f}ms")
    assert health.status_code == 200
    assert health.json()["code"] == 0
    assert health_ms < 1000, f"/health 被推理阻塞，耗时 {health_ms:.0f}ms（应秒回）"
