# -*- coding: utf-8 -*-
"""YOLO11s 检测服务（同步推理 + 事件循环友好入口）。

调用范式严格对齐 ``scripts/test_yolo.py``：
``YOLO(ckpt).predict(img, conf=..., verbose=False)[0]``，从 ``res.boxes`` 取
``.cls``/``.conf``/``.xyxy``，``res.plot()`` 出标注图。
"""
from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.core.concurrency import run_in_pool
from app.core.exceptions import InferenceError, ModelLoadError
from app.services.annotate import annotate_boxes_cn
from app.utils.image import bbox_area


@dataclass
class DetBox:
    """单个检测框。"""

    cls_id: int
    label: str
    conf: float
    bbox: list[int]  # [x1, y1, x2, y2] 绝对像素


@dataclass
class DetectionResult:
    """一次推理的完整结果。"""

    boxes: list[DetBox]
    top_label: str | None
    top_conf: float | None
    spot_count: int
    area_ratio: float  # 病斑面积和 / 图像面积，≤ 1
    annotated_bgr: np.ndarray  # res.plot() 结果图


class YoloDetector:
    """YOLO 检测器单例封装。"""

    def __init__(self) -> None:
        self._model = None
        self._names: dict[int, str] = {}

    def load(self) -> None:
        """加载 YOLO 权重；启动时调用一次。失败抛 ``ModelLoadError``。"""
        if self._model is not None:
            return
        weights = settings.yolo_weights_abs
        if not weights.exists():
            raise ModelLoadError(f"YOLO 权重文件不存在：{weights}")
        try:
            from ultralytics import YOLO

            self._model = YOLO(str(weights))
            # model.names 形如 {0: "Apple___Apple_scab", ...}
            self._names = {int(k): str(v) for k, v in dict(self._model.names).items()}
        except Exception as exc:  # noqa: BLE001 —— 统一包装为模型加载错误
            raise ModelLoadError(f"YOLO 权重加载失败：{exc}") from exc

    @property
    def names(self) -> dict[int, str]:
        """类别 id → 类别名。"""
        return self._names

    @property
    def loaded(self) -> bool:
        """模型是否已加载。"""
        return self._model is not None

    def infer(self, image_bgr: np.ndarray, conf: float | None = None) -> DetectionResult:
        """同步推理（CPU）。调用方须用线程池包裹，避免阻塞事件循环。"""
        if self._model is None:
            raise ModelLoadError("YOLO 模型尚未加载，请先调用 load()")
        conf_thr = settings.yolo_conf_threshold if conf is None else conf
        try:
            res = self._model.predict(image_bgr, conf=conf_thr, verbose=False)[0]
            height, width = image_bgr.shape[:2]
            image_area = float(height * width) or 1.0

            boxes: list[DetBox] = []
            total_area = 0.0
            raw = res.boxes
            if raw is not None and len(raw) > 0:
                cls_ids = raw.cls.tolist()
                confs = raw.conf.tolist()
                xyxys = raw.xyxy.tolist()
                for cls_id, score, xyxy in zip(cls_ids, confs, xyxys):
                    cid = int(cls_id)
                    x1, y1, x2, y2 = (int(round(float(v))) for v in xyxy)
                    bbox = [x1, y1, x2, y2]
                    boxes.append(
                        DetBox(
                            cls_id=cid,
                            label=self._names.get(cid, str(cid)),
                            conf=float(score),
                            bbox=bbox,
                        )
                    )
                    total_area += bbox_area(bbox)

            boxes.sort(key=lambda b: b.conf, reverse=True)
            top = boxes[0] if boxes else None
            area_ratio = min(1.0, total_area / image_area)
            annotated_bgr = self._plot_annotated(res, boxes)
            return DetectionResult(
                boxes=boxes,
                top_label=top.label if top else None,
                top_conf=top.conf if top else None,
                spot_count=len(boxes),
                area_ratio=area_ratio,
                annotated_bgr=annotated_bgr,
            )
        except ModelLoadError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 统一包装为推理错误
            raise InferenceError(f"YOLO 推理失败：{exc}") from exc

    @staticmethod
    def _plot_annotated(res, boxes: list[DetBox]) -> "np.ndarray":
        """构建标注图：先画框（无文字），再烧写中文标签。

        ``cv2.putText`` 不支持中文，故标签由 PIL 绘制（见 ``services/annotate.py``）；
        字体不可用 / 绘制失败时回退 ``res.plot()`` 英文标注，不让检测失败。
        """
        try:
            base = res.plot(labels=False)
        except TypeError:  # noqa: TRY301 —— 旧版 ultralytics 无 labels 参数
            base = res.plot()
        if boxes:
            annotated = annotate_boxes_cn(base, boxes)
            if annotated is not None:
                return annotated
        return res.plot()


# 模块级单例
detector = YoloDetector()


async def infer_async(image_bgr: np.ndarray, conf: float | None = None) -> DetectionResult:
    """事件循环友好入口：内部把 ``detector.infer`` 提交到受限线程池。"""
    return await run_in_pool(detector.infer, image_bgr, conf)


def is_loaded() -> bool:
    """健康检查用：YOLO 是否已就绪。"""
    return detector.loaded


__all__ = ["DetBox", "DetectionResult", "YoloDetector", "detector", "infer_async", "is_loaded"]
