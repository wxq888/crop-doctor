# -*- coding: utf-8 -*-
"""disease_weather_rules 病害-气象规则 与 alert_records 预警记录。"""
from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin

# 降雨条件
RAIN_CONDITION_ENUM = Enum("any", "rain", "no_rain", name="rain_condition", native_enum=True)
# 风险等级
RISK_LEVEL_ENUM = Enum("high", "mid", "low", name="risk_level", native_enum=True)
# 预警来源
ALERT_SOURCE_ENUM = Enum("weather", "detection", name="alert_source", native_enum=True)


class DiseaseWeatherRule(Base, TimestampMixin):
    """病害爆发的气象条件规则。"""

    __tablename__ = "disease_weather_rules"
    __table_args__ = (
        Index("ix_rule_disease", "disease"),
        Index("ix_rule_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    disease: Mapped[str] = mapped_column(String(100), nullable=False)
    crop: Mapped[str | None] = mapped_column(String(50), nullable=True)
    temp_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    rain_condition: Mapped[str] = mapped_column(
        RAIN_CONDITION_ENUM,
        nullable=False,
        default="any",
        server_default="any",
    )
    risk_level: Mapped[str] = mapped_column(RISK_LEVEL_ENUM, nullable=False)
    advice: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")


class AlertRecord(Base, CreatedAtMixin):
    """预警记录（天气驱动为主）。"""

    __tablename__ = "alert_records"
    __table_args__ = (
        Index("ix_alert_source", "source"),
        Index("ix_alert_disease", "disease"),
        Index("ix_alert_risk", "risk_level"),
        Index("ix_alert_user", "user_id"),
        Index("ix_alert_read", "is_read"),
        Index("ix_alert_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(
        ALERT_SOURCE_ENUM,
        nullable=False,
        default="weather",
        server_default="weather",
    )
    disease: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[str] = mapped_column(RISK_LEVEL_ENUM, nullable=False)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    # NULL=全局广播；非空=定向用户
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_alert_records_user"),
        nullable=True,
    )
    location: Mapped[str | None] = mapped_column(String(50), nullable=True)
    forecast_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_read: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
