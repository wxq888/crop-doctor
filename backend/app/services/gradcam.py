# -*- coding: utf-8 -*-
"""Grad-CAM 可解释性服务（ResNet50 旁支模型，异步生成热力图）。

- 懒加载：首次请求才加载 ResNet50，线程锁保护只加载一次，之后常驻内存。
- 预处理与 ``scripts/test_model.py`` 一致：Resize(224) → ToTensor → ImageNet 归一化。
- 权重为 dict：``{"classes", "state_dict"}``，target layer = ``model.layer4``。
"""
import threading
from dataclasses import dataclass

import numpy as np
from loguru import logger

from app.core.concurrency import run_in_pool
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import GradCamDisabledError, GradCamError
from app.models.detection import DetectionRecord
from app.utils import storage
from app.utils.image import imread_cn, imwrite_cn


@dataclass
class GradCamResult:
    """Grad-CAM 生成结果。"""

    overlay_bgr: np.ndarray
    label: str
    conf: float
    layer: str = "layer4"


class GradCamService:
    """ResNet50 + Grad-CAM 单例封装（懒加载）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._classes: list[str] = []
        self._cam = None
        self._tf = None
        self._device = "cpu"

    def ensure_loaded(self) -> None:
        """懒加载 ResNet50 + GradCAM；线程锁保护只加载一次。

        ``GRADCAM_ENABLED=false`` → 抛 ``GradCamDisabledError``。
        """
        if not settings.gradcam_enabled:
            raise GradCamDisabledError()
        if self._model is not None:
            return
        with self._lock:
            # 双重检查：避免竞态下重复加载
            if self._model is not None:
                return
            weights = settings.resnet_weights_abs
            if not weights.exists():
                raise GradCamError(f"ResNet50 权重文件不存在：{weights}")
            try:
                import torch
                from pytorch_grad_cam import GradCAM
                from torchvision import models, transforms

                device = "cuda" if torch.cuda.is_available() else "cpu"
                try:
                    ckpt = torch.load(str(weights), map_location=device, weights_only=False)
                except TypeError:  # 兼容无 weights_only 参数的旧版 torch
                    ckpt = torch.load(str(weights), map_location=device)

                classes = list(ckpt["classes"])
                model = models.resnet50()
                model.fc = torch.nn.Linear(model.fc.in_features, len(classes))
                model.load_state_dict(ckpt["state_dict"])
                model.eval().to(device)
                cam = GradCAM(model=model, target_layers=[model.layer4])
                tf = transforms.Compose(
                    [
                        transforms.ToPILImage(),
                        transforms.Resize((224, 224)),
                        transforms.ToTensor(),
                        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
                    ]
                )
                self._model, self._classes, self._cam, self._tf, self._device = (
                    model,
                    classes,
                    cam,
                    tf,
                    device,
                )
                logger.info(f"ResNet50 加载完成：{len(classes)} 类，设备 {device}")
            except GradCamError:
                raise
            except Exception as exc:  # noqa: BLE001 —— 统一包装
                raise GradCamError(f"ResNet50 加载失败：{exc}") from exc

    def generate(self, image_bgr: np.ndarray) -> GradCamResult:
        """同步重计算（CPU 约 1~3s）。调用方须放线程池。"""
        self.ensure_loaded()
        try:
            import cv2
            import torch
            from pytorch_grad_cam.utils.image import show_cam_on_image
            from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget

            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            tensor = self._tf(rgb).unsqueeze(0).to(self._device)

            with torch.no_grad():
                prob = torch.softmax(self._model(tensor), 1)[0]
            cls_id = int(torch.argmax(prob))
            label = self._classes[cls_id]
            conf = float(prob[cls_id])

            heatmap = self._cam(input_tensor=tensor, targets=[ClassifierOutputTarget(cls_id)])[0]
            heat = cv2.resize(heatmap, (rgb.shape[1], rgb.shape[0]))
            overlay = show_cam_on_image(rgb.astype(np.float32) / 255.0, heat, use_rgb=True)
            overlay_bgr = cv2.cvtColor((overlay * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
            return GradCamResult(overlay_bgr=overlay_bgr, label=label, conf=conf)
        except GradCamError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 统一包装
            raise GradCamError(f"Grad-CAM 生成失败：{exc}") from exc

    def reset(self) -> None:
        """释放已加载模型（权重热切换时使用），下次 ``ensure_loaded`` 重载。"""
        with self._lock:
            self._model = None
            self._classes = []
            self._cam = None
            self._tf = None


# 模块级单例
gradcam = GradCamService()


async def generate_to_file(image_bgr: np.ndarray, out_abs_path: str) -> GradCamResult:
    """线程池内生成 + 落盘（中文路径安全）。供 BackgroundTasks 调用。"""
    result = await run_in_pool(gradcam.generate, image_bgr)
    ok = await run_in_pool(imwrite_cn, out_abs_path, result.overlay_bgr)
    if not ok:
        raise GradCamError(f"热力图落盘失败：{out_abs_path}")
    return result


async def run_gradcam_job(record_id: int) -> None:
    """后台任务：读记录 → 重读原图 → 生成 → 回写 ``gradcam_path`` / ``gradcam_status``。

    任何异常均被捕获并写日志，状态置 ``failed``；绝不让后台任务拖垮进程。
    """
    db = SessionLocal()
    try:
        record = db.get(DetectionRecord, record_id)
        if record is None:
            logger.warning(f"Grad-CAM 任务：记录 {record_id} 不存在，跳过")
            return

        if not settings.gradcam_enabled:
            record.gradcam_status = "skipped"
            db.commit()
            logger.info(f"Grad-CAM 已禁用，记录 {record_id} 置 skipped")
            return

        image = imread_cn(storage.abs_path(record.image_path))
        if image is None:
            record.gradcam_status = "failed"
            db.commit()
            logger.warning(f"Grad-CAM 任务：记录 {record_id} 原图读取失败")
            return

        out_rel = storage.rel_path(storage.CAM_DIR, f"{record_id}.jpg")
        out_abs = str(storage.abs_path(out_rel))
        result = await generate_to_file(image, out_abs)

        record.gradcam_path = out_rel
        record.gradcam_status = "done"
        db.commit()
        logger.info(
            f"Grad-CAM 完成：记录 {record_id} → {out_rel}（{result.label} {result.conf:.2f}）"
        )
    except Exception:  # noqa: BLE001 —— 后台任务必须吞异常但留痕
        logger.exception(f"Grad-CAM 后台任务异常：记录 {record_id}")
        try:
            db.rollback()
            record = db.get(DetectionRecord, record_id)
            if record is not None:
                record.gradcam_status = "failed"
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception(f"Grad-CAM 状态回写失败：记录 {record_id}")
    finally:
        db.close()


__all__ = [
    "GradCamResult",
    "GradCamService",
    "gradcam",
    "generate_to_file",
    "run_gradcam_job",
]
