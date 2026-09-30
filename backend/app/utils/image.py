# -*- coding: utf-8 -*-
"""图像工具：中文路径读写、ndarray↔bytes、边界框面积。

Windows 下 ``cv2.imread`` / ``cv2.imwrite`` 无法处理中文路径，统一改用
``np.fromfile`` + ``cv2.imdecode`` / ``cv2.imencode`` + ``tofile``。
"""
import os

import cv2
import numpy as np


def imread_cn(path: "str | os.PathLike[str]") -> np.ndarray | None:
    """读取图片（兼容中文路径），返回 BGR ndarray；失败返回 None。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_cn(path: "str | os.PathLike[str]", img_bgr: np.ndarray) -> bool:
    """保存图片（兼容中文路径），成功返回 True。"""
    ext = os.path.splitext(str(path))[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img_bgr)
    if ok:
        buf.tofile(str(path))
    return bool(ok)


def bytes_to_ndarray(data: bytes) -> np.ndarray | None:
    """把上传的字节流解码为 BGR ndarray；失败返回 None。"""
    if not data:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def ndarray_to_bytes(img_bgr: np.ndarray, ext: str = ".jpg") -> bytes:
    """把 BGR ndarray 编码为字节流。"""
    if not ext.startswith("."):
        ext = "." + ext
    ok, buf = cv2.imencode(ext, img_bgr)
    if not ok:
        raise ValueError("图像编码失败")
    return buf.tobytes()


def bbox_area(bbox: "list[int] | tuple[int, int, int, int]") -> float:
    """计算 ``[x1,y1,x2,y2]`` 边界框面积（绝对像素，负值归零）。"""
    x1, y1, x2, y2 = bbox
    return max(0.0, float(x2) - float(x1)) * max(0.0, float(y2) - float(y1))


__all__ = [
    "imread_cn",
    "imwrite_cn",
    "bytes_to_ndarray",
    "ndarray_to_bytes",
    "bbox_area",
]
