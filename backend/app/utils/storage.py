# -*- coding: utf-8 -*-
"""上传产物存储：目录管理、文件名生成、URL 拼装。

目录结构（相对 ``settings.upload_path``）::

    images/     原图
    annotated/  带检测框的结果图
    gradcam/    Grad-CAM 热力图

数据库存**相对路径**，出参统一拼 ``/static/<rel>`` 绝对 URL。
"""
import uuid
from pathlib import Path

from app.core.config import settings

# 子目录名常量
IMG_DIR = "images"
ANN_DIR = "annotated"
CAM_DIR = "gradcam"
ALL_SUB_DIRS = (IMG_DIR, ANN_DIR, CAM_DIR)

# 上传白名单
ALLOWED_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CONTENT_TYPES: set[str] = {"image/jpeg", "image/png", "image/webp"}


def ensure_dirs() -> None:
    """确保三个上传子目录存在。"""
    for sub in ALL_SUB_DIRS:
        (settings.upload_path / sub).mkdir(parents=True, exist_ok=True)


def gen_filename(original_name: str) -> str:
    """基于原始扩展名生成 ``uuid4().hex + ext`` 的安全文件名（防中文/冲突）。"""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"
    return f"{uuid.uuid4().hex}{ext}"


def rel_path(sub_dir: str, filename: str) -> str:
    """拼装相对路径（存库用），统一用正斜杠。"""
    return f"{sub_dir}/{filename}"


def abs_path(rel: str) -> Path:
    """相对路径 → 绝对路径。"""
    return settings.upload_path / rel


def url_of(rel: str | None) -> str | None:
    """相对路径 → 静态资源 URL；``None`` 原样返回。"""
    if not rel:
        return None
    return f"/static/{rel}"


__all__ = [
    "IMG_DIR",
    "ANN_DIR",
    "CAM_DIR",
    "ALL_SUB_DIRS",
    "ALLOWED_EXTENSIONS",
    "ALLOWED_CONTENT_TYPES",
    "ensure_dirs",
    "gen_filename",
    "rel_path",
    "abs_path",
    "url_of",
]
