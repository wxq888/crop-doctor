# -*- coding: utf-8 -*-
"""检测相关 Schema。"""
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class DetBox(BaseModel):
    """单个检测框出参。"""

    model_config = ConfigDict(from_attributes=True)

    class_name: str
    conf: float
    bbox: list[int] = Field(default_factory=list, description="[x1,y1,x2,y2] 绝对像素")


class DetectionRecordOut(BaseModel):
    """检测结果出参（创建检测后立即返回）。"""

    id: int
    severity_level: int
    severity_label: str
    top_disease: str | None = None
    top_conf: float | None = None
    # 中文名与健康标记（由 class-map 派生；带默认值，旧调用方/旧前端不炸）
    disease_cn: str | None = None
    crop_cn: str | None = None
    is_healthy: bool = False
    spot_count: int
    area_ratio: float
    image_url: str | None = None
    annotated_url: str | None = None
    gradcam_status: str
    details: list[DetBox] = Field(default_factory=list)
    created_at: UtcDatetime


class DetectionListItem(BaseModel):
    """检测记录列表项。"""

    id: int
    thumb_url: str | None = None
    top_disease: str | None = None
    severity_level: int
    severity_label: str
    # 与详情口径一致的中文字段
    disease_cn: str | None = None
    is_healthy: bool = False
    created_at: UtcDatetime


class DetectionDetailOut(DetectionRecordOut):
    """检测记录详情（在记录基础上追加热力图 / 作物 / 位置）。"""

    gradcam_url: str | None = None
    crop: str | None = None
    location: str | None = None


class GradCamStatusOut(BaseModel):
    """热力图状态出参。"""

    status: str
    url: str | None = None


__all__ = [
    "DetBox",
    "DetectionRecordOut",
    "DetectionListItem",
    "DetectionDetailOut",
    "GradCamStatusOut",
]
