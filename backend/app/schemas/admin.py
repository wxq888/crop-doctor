# -*- coding: utf-8 -*-
"""admin 模块 Schema：统计 / 用户 / 全局检测 / 模型。

设计依据：``docs/impl-pc-admin-v1.md`` §2.1。

口径说明（team-lead 裁决 #1）：**我们没有真值标签，绝不把平均置信度标成"准确率"**。
故统计拆为两个诚实指标：``today_avg_conf``（今日平均置信度 = ``top_conf`` 均值）
与 ``today_healthy_rate``（今日健康率 = ``severity_level==0`` 占比）。UI/API 均不得出现"准确率"字样。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime
from app.schemas.detection import DetectionDetailOut


class StatsOverview(BaseModel):
    """大屏顶部 8 项概览统计（全部 SQL 聚合，不触发任何 LLM 调用）。"""

    today_detections: int = 0
    today_new_users: int = 0
    total_users: int = 0
    total_detections: int = 0
    today_healthy_rate: float = 0.0  # 今日健康率（severity_level==0 占比）
    today_avg_conf: float = 0.0  # 今日平均置信度（top_conf 均值）
    warnings_active: int = 0  # 近 24h 生效预警数
    pending_feedbacks: int = 0  # status='pending' 工单数


class StatsTrend(BaseModel):
    """大屏趋势 / 排行 / 分布（近 N 日，按 UTC 日期）。"""

    days: list[str] = Field(default_factory=list)  # ["2026-09-11", ...]
    detections: list[int] = Field(default_factory=list)
    healthy: list[int] = Field(default_factory=list)
    warnings: list[int] = Field(default_factory=list)
    disease_rank: list[dict] = Field(default_factory=list)  # [{disease,disease_cn,count}] Top10
    severity_dist: list[dict] = Field(default_factory=list)  # [{level,label,count}] 0..3
    by_crop: list[dict] = Field(default_factory=list)  # [{crop,crop_cn,count}]


class AdminUserItem(BaseModel):
    """用户列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    role: str
    status: int
    created_at: UtcDatetime
    detection_count: int = 0
    feedback_count: int = 0


class AdminUserDetail(AdminUserItem):
    """用户详情（含头像 / 手机号 / 预警数，用于抽屉三 tab）。"""

    avatar: str | None = None
    phone: str | None = None
    warning_count: int = 0


class AdminDetectionItem(BaseModel):
    """全局检测记录列表项（= DetectionListItem + 用户/置信度/反馈状态）。"""

    id: int
    thumb_url: str | None = None
    top_disease: str | None = None
    disease_cn: str | None = None
    crop: str | None = None
    crop_cn: str | None = None
    severity_level: int = 0
    severity_label: str = "未知"
    top_conf: float | None = None
    user_id: int
    username: str | None = None
    feedback_status: str | None = None
    created_at: UtcDatetime


class AdminDetectionDetail(DetectionDetailOut):
    """全局检测记录详情（admin 可查任意用户，属隔离红线的唯一合法越权入口）。"""

    user_id: int
    username: str | None = None
    disease_cn: str | None = None
    crop_cn: str | None = None


class ModelInfo(BaseModel):
    """单个模型权重信息。"""

    filename: str
    size_mb: float
    modified_at: UtcDatetime
    is_active: bool = False


class ModelListOut(BaseModel):
    """模型管理出参。"""

    items: list[ModelInfo] = Field(default_factory=list)
    active: str
    loaded: bool = False


class UserStatusIn(BaseModel):
    """启停用户入参。"""

    status: int = Field(ge=0, le=1, description="1=启用，0=禁用")


class ResetPasswordIn(BaseModel):
    """重置密码入参（``new_password`` 为空则服务端生成强随机密码）。"""

    new_password: str | None = Field(default=None, min_length=6, max_length=64)


class ResetPasswordOut(BaseModel):
    """重置密码出参。"""

    username: str
    new_password: str


class ModelActivateIn(BaseModel):
    """模型热切换入参。"""

    filename: str = Field(min_length=1, max_length=200)


__all__ = [
    "StatsOverview",
    "StatsTrend",
    "AdminUserItem",
    "AdminUserDetail",
    "AdminDetectionItem",
    "AdminDetectionDetail",
    "ModelInfo",
    "ModelListOut",
    "UserStatusIn",
    "ResetPasswordIn",
    "ResetPasswordOut",
    "ModelActivateIn",
]
