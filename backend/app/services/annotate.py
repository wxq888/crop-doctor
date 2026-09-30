# -*- coding: utf-8 -*-
"""标注图中文烧字（PIL 绘制）。

``cv2.putText`` 不支持中文（非 ASCII 一律变 ``?``），因此标注文字统一改用
PIL ``ImageDraw`` 绘制：调用方先用 YOLO ``res.plot(labels=False)`` 画出检测框
（不含文字），本模块在框上方烧写「中文类名 0.87」。

字体优先微软雅黑（Windows 自带 ``msyh.ttc``），逐个候选回退；全部加载失败时
返回 ``None``，由调用方回退英文标注（``res.plot()``），**绝不因字体缺失让
检测主链路失败**。任何绘制异常同样降级返回 ``None``。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.services.classmap import disease_cn_of

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.services.yolo_infer import DetBox

# 中文字体候选（按优先级；均为 Windows 常见自带字体）
_FONT_CANDIDATES: tuple[str, ...] = (
    "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",  # 黑体
    "C:/Windows/Fonts/simsun.ttc",  # 宋体
)

# 标签底色（RGB，品牌绿）与文字色
_LABEL_BG_RGB = (43, 164, 113)
_LABEL_TEXT_RGB = (255, 255, 255)


def _load_font(size: int) -> ImageFont.FreeTypeFont | None:
    """按候选列表加载中文字体；全部失败返回 None。"""
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def annotate_boxes_cn(img_bgr: np.ndarray, boxes: "Iterable[DetBox]") -> np.ndarray | None:
    """在 BGR 标注图上为每个检测框烧写中文标签。

    标签形如「马铃薯健康叶 0.87」，绘制在框内顶部（贴上边界时画到框下方）。
    字体不可用或绘制异常时返回 ``None``（调用方回退英文标注）。
    """
    try:
        height, width = img_bgr.shape[:2]
        font = _load_font(max(14, height // 30))
        if font is None:
            return None

        pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        for box in boxes:
            x1, y1, x2, y2 = box.bbox
            text = f"{disease_cn_of(box.label)} {box.conf:.2f}"
            tb = draw.textbbox((0, 0), text, font=font)
            text_w, text_h = tb[2] - tb[0], tb[3] - tb[1]
            pad = 4
            # 底色块位置：默认贴框内顶部；贴近图像上边界时画到框下方
            ty = y1 - text_h - pad * 2
            if ty < 0:
                ty = min(y1 + 2, height - text_h - pad * 2)
            ty = max(0, ty)
            # 水平方向钳制在图像内
            tx = max(0, min(x1, width - text_w - pad * 2))
            draw.rectangle(
                [tx, ty, tx + text_w + pad * 2, ty + text_h + pad * 2],
                fill=_LABEL_BG_RGB,
            )
            draw.text(
                (tx + pad, ty + pad - tb[1]),
                text,
                font=font,
                fill=_LABEL_TEXT_RGB,
            )
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:  # noqa: BLE001 —— 绘制失败一律降级为英文标注
        return None


__all__ = ["annotate_boxes_cn"]
