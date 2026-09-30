# -*- coding: utf-8 -*-
"""上传校验与落盘隔离测试。

覆盖：空文件 / 非图片内容 / 扩展名白名单 / content_type 白名单 / 大小上限 /
png·webp 支持 / 大小写扩展名；并断言"上传落盘只写隔离临时目录，不写真实
``backend/uploads/``"（修复测试污染仓库的根因）。
"""
import pytest

from app.core.config import REPO_ROOT
from tests.conftest import auth_headers, count_upload_files, jpeg_bytes, png_bytes, webp_bytes

DET = "/api/v1/detection"


def _post(client, token: str, filename: str, content: bytes, content_type: str):
    return client.post(
        f"{DET}/image",
        headers=auth_headers(token),
        files={"file": (filename, content, content_type)},
    )


def test_empty_file_rejected(client, make_user, stub_gradcam) -> None:
    """空文件 → 400 / 2001（无法解析）。"""
    token, _ = make_user("up_empty")
    resp = _post(client, token, "empty.jpg", b"", "image/jpeg")
    assert resp.status_code == 400
    assert resp.json()["code"] == 2001


def test_non_image_content_rejected(client, make_user, stub_gradcam) -> None:
    """扩展名/类型伪装成 jpg 但内容非图片 → 400 / 2001。"""
    token, _ = make_user("up_fake")
    resp = _post(client, token, "fake.jpg", b"this is definitely not an image", "image/jpeg")
    assert resp.status_code == 400
    assert resp.json()["code"] == 2001


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("leaf.gif", "image/gif", b"GIF89a"),        # 扩展名不在白名单
        ("leaf.jpg", "text/plain", b"hello"),        # content_type 不在白名单
        ("leaf", "image/jpeg", b"hello"),            # 无扩展名
        ("leaf.svg", "image/svg+xml", b"<svg/>"),    # 扩展名与类型均不在白名单
    ],
)
def test_whitelist_rejects(client, make_user, stub_gradcam, filename, content_type, content) -> None:
    """扩展名 / content_type 白名单外的上传一律 400 / 2001。"""
    token, _ = make_user(f"up_wl_{filename.replace('.', '_')}")
    resp = _post(client, token, filename, content, content_type)
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 2001


def test_png_accepted(client, make_user, stub_infer, stub_gradcam) -> None:
    """PNG 合法图片可被接受 → 200。"""
    stub_infer(spot_count=1)
    token, _ = make_user("up_png")
    resp = _post(client, token, "leaf.png", png_bytes(), "image/png")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["image_url"].endswith(".png")


def test_uppercase_extension_accepted(client, make_user, stub_infer, stub_gradcam) -> None:
    """大写扩展名（.JPG）应被规范化后接受 → 200。"""
    stub_infer(spot_count=1)
    token, _ = make_user("up_upper")
    resp = _post(client, token, "LEAF.JPG", jpeg_bytes(), "image/jpeg")
    assert resp.status_code == 200, resp.text


def test_webp_accepted_when_supported(client, make_user, stub_infer, stub_gradcam) -> None:
    """WEBP 合法图片可被接受（当前 OpenCV 不支持编码时跳过）。"""
    payload = webp_bytes()
    if payload is None:
        pytest.skip("当前 OpenCV 构建不支持 WEBP 编码")
    stub_infer(spot_count=1)
    token, _ = make_user("up_webp")
    resp = _post(client, token, "leaf.webp", payload, "image/webp")
    assert resp.status_code == 200, resp.text


def test_oversized_rejected(client, make_user, stub_gradcam) -> None:
    """恰好超过上限 1 字节 → 413 / 2002。"""
    from app.core.config import settings

    token, _ = make_user("up_big")
    big = b"\xff" * (settings.max_upload_mb * 1024 * 1024 + 1)
    resp = _post(client, token, "big.jpg", big, "image/jpeg")
    assert resp.status_code == 413
    assert resp.json()["code"] == 2002


def test_successful_upload_writes_two_files_to_isolated_dir(
    client, make_user, create_record, upload_dir
) -> None:
    """成功检测后，原图 + 标注图落在隔离目录（共 2 个文件）。"""
    token, _ = make_user("up_disk")
    rec = create_record(token)

    assert count_upload_files(upload_dir) == 2
    img_name = rec["image_url"].rsplit("/", 1)[-1]
    ann_name = rec["annotated_url"].rsplit("/", 1)[-1]
    assert (upload_dir / "images" / img_name).is_file()
    assert (upload_dir / "annotated" / ann_name).is_file()


def test_upload_never_touches_real_upload_dir(client, make_user, create_record) -> None:
    """上传落盘绝不写入仓库真实 ``backend/uploads/``（磁盘卫生回归）。"""
    real_dir = REPO_ROOT / "backend" / "uploads"
    before = count_upload_files(real_dir)

    token, _ = make_user("up_real")
    create_record(token)
    create_record(token)

    after = count_upload_files(real_dir)
    assert after == before, f"真实上传目录被污染：{before} → {after}"
