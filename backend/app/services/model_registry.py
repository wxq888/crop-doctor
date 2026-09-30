# -*- coding: utf-8 -*-
"""模型权重注册表：列出版本 / 读取生效权重 / 持久化 / 热切换。

设计依据：``docs/impl-pc-admin-v1.md`` §2.1（``GET /admin/model``、``POST /admin/model/activate``）
与 team-lead 裁决 #2：**热切换持久化到 ``ml/exports/active_model.json``**（不进 DB、不加表），
重启后仍生效；文件缺失时回退 ``.env`` 的 ``YOLO_WEIGHTS_PATH`` 默认权重。

路径经模块级函数 ``exports_dir()`` / ``active_file()`` 间接获取，便于单测用 monkeypatch 隔离到 tmp 目录。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.core.exceptions import ModelUnavailableError

# 仅识别 YOLO 权重后缀
_WEIGHT_SUFFIXES = (".pt", ".pth")
_ACTIVE_FILE_NAME = "active_model.json"


def exports_dir() -> Path:
    """``ml/exports`` 权重目录（可被测试 monkeypatch 到 tmp 目录）。"""
    return settings.ml_exports_path


def active_file() -> Path:
    """生效权重的持久化文件（可被测试 monkeypatch）。"""
    return exports_dir() / _ACTIVE_FILE_NAME


def default_model_name() -> str:
    """``.env`` 配置的默认权重文件名。"""
    return Path(settings.yolo_weights_path).name


def list_weight_files() -> list[Path]:
    """列出 ``ml/exports`` 下的所有权重文件（按文件名升序）。"""
    directory = exports_dir()
    if not directory.exists():
        return []
    files = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _WEIGHT_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.name.lower())


def active_model_name() -> str:
    """读取当前生效权重文件名；持久化文件缺失 / 失效时回退默认权重。"""
    path = active_file()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            name = str(data.get("filename") or "").strip()
            if name and (exports_dir() / name).exists():
                return name
            if name:
                logger.warning(f"生效权重 {name} 不存在，回退默认权重 {default_model_name()}")
    except (OSError, ValueError) as exc:
        logger.warning(f"生效权重文件解析失败，回退默认权重：{exc}")
    return default_model_name()


def persist_active_model(filename: str) -> None:
    """把生效权重文件名写入 ``active_model.json``（重启后仍生效）。"""
    path = active_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "filename": filename,
            "activated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise ModelUnavailableError(f"生效权重记录写入失败：{exc}") from exc


def clear_active_model() -> None:
    """删除持久化的生效权重（回退默认权重；仅测试/运维用）。"""
    try:
        active_file().unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001
        logger.warning(f"删除生效权重记录失败：{exc}")


def reload_detector(filename: str) -> None:
    """把 YOLO 检测器热切换到指定权重（CPU 重载，数秒）。

    通过清空 ``yolo_infer.detector`` 的内部模型句柄强制重新加载，**不修改 yolo_infer.py**；
    失败时尽力回退到切换前的权重，并抛 ``8003``。
    """
    from app.services import yolo_infer  # 惰性导入，避免测试期触发重量级依赖

    target = exports_dir() / filename
    if not target.exists():
        raise ModelUnavailableError(f"模型文件不存在：{filename}")

    previous = settings.yolo_weights_path
    settings.yolo_weights_path = str(target)
    detector = yolo_infer.detector
    try:
        detector._model = None  # noqa: SLF001 —— 强制重载：清空既有句柄
        detector._names = {}
        detector.load()
    except Exception as exc:  # noqa: BLE001 —— 统一包装为 8003，并尽力回退
        settings.yolo_weights_path = previous
        try:
            detector._model = None  # noqa: SLF001
            detector._names = {}
            detector.load()
        except Exception:  # noqa: BLE001 —— 回退失败仅记日志，原错误更关键
            logger.warning("热切换失败后回退旧权重也失败")
        raise ModelUnavailableError(f"模型热切换失败：{exc}") from exc


__all__ = [
    "exports_dir",
    "active_file",
    "default_model_name",
    "list_weight_files",
    "active_model_name",
    "persist_active_model",
    "clear_active_model",
    "reload_detector",
]
