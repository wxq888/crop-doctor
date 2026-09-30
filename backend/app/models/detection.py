# -*- coding: utf-8 -*-
"""detection_records 检测记录（头）与 detection_details 检测明细（每框一行）。"""
from datetime import datetime

from sqlalchemy import (
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

# 异步 Grad-CAM 状态
GRADCAM_STATUS_ENUM = Enum(
    "pending",
    "done",
    "failed",
    "skipped",
    name="gradcam_status",
    native_enum=True,
)


class DetectionRecord(Base, CreatedAtMixin):
    """一次图片检测的汇总记录。"""

    __tablename__ = "detection_records"
    __table_args__ = (
        Index("ix_det_user", "user_id"),
        Index("ix_det_severity", "severity_level"),
        Index("ix_det_top_disease", "top_disease"),
        Index("ix_det_crop", "crop"),
        Index("ix_det_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 数据隔离键：所有查询强制按此过滤
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_detection_records_user"),
        nullable=False,
    )
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    annotated_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    spot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    area_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    top_disease: Mapped[str | None] = mapped_column(String(100), nullable=True)
    top_conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    crop: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gradcam_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gradcam_status: Mapped[str] = mapped_column(
        GRADCAM_STATUS_ENUM,
        nullable=False,
        default="pending",
        server_default="pending",
    )

    details: Mapped[list["DetectionDetail"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DetectionDetail(Base, CreatedAtMixin):
    """检测明细：每个检测框一行。"""

    __tablename__ = "detection_details"
    __table_args__ = (Index("ix_detdetail_record", "record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("detection_records.id", name="fk_detection_details_record", ondelete="CASCADE"),
        nullable=False,
    )
    class_name: Mapped[str] = mapped_column(String(100), nullable=False)
    conf: Mapped[float] = mapped_column(Float, nullable=False)
    # [x1, y1, x2, y2] 绝对像素
    bbox: Mapped[list] = mapped_column(JSON, nullable=False)

    record: Mapped[DetectionRecord] = relationship(back_populates="details")
