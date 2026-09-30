# -*- coding: utf-8 -*-
"""初始建表：10 张业务表（含 Phase 2 表，一次建全）。

Revision ID: 0001_initial
Revises:
Create Date: 2025-06-01 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 统一的 InnoDB / utf8mb4 参数
_TABLE_KW = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

# 常用类型别名
_PK = mysql.BIGINT(unsigned=True)
_FK = mysql.BIGINT(unsigned=True)
_BOOL = mysql.TINYINT(display_width=1)
_NOW = sa.text("CURRENT_TIMESTAMP")
_NOW_UPDATE = sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")


def upgrade() -> None:
    """建全部业务表。"""

    # ===== users =====
    op.create_table(
        "users",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("nickname", sa.String(50), nullable=True),
        sa.Column("role", sa.Enum("user", "admin", name="role"), nullable=False, server_default="user"),
        sa.Column("avatar", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("status", _BOOL, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW_UPDATE),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        **_TABLE_KW,
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    # ===== detection_records =====
    op.create_table(
        "detection_records",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("user_id", _FK, nullable=False),
        sa.Column("image_path", sa.String(255), nullable=False),
        sa.Column("annotated_path", sa.String(255), nullable=True),
        sa.Column("severity_level", mysql.TINYINT(), nullable=False, server_default="0"),
        sa.Column("spot_count", mysql.INTEGER(), nullable=False, server_default="0"),
        sa.Column("area_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("top_disease", sa.String(100), nullable=True),
        sa.Column("top_conf", sa.Float(), nullable=True),
        sa.Column("crop", sa.String(50), nullable=True),
        sa.Column("location", sa.String(50), nullable=True),
        sa.Column("gradcam_path", sa.String(255), nullable=True),
        sa.Column(
            "gradcam_status",
            sa.Enum("pending", "done", "failed", "skipped", name="gradcam_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_detection_records_user"),
        **_TABLE_KW,
    )
    op.create_index("ix_det_user", "detection_records", ["user_id"])
    op.create_index("ix_det_severity", "detection_records", ["severity_level"])
    op.create_index("ix_det_top_disease", "detection_records", ["top_disease"])
    op.create_index("ix_det_crop", "detection_records", ["crop"])
    op.create_index("ix_det_created", "detection_records", ["created_at"])

    # ===== detection_details =====
    op.create_table(
        "detection_details",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("record_id", _FK, nullable=False),
        sa.Column("class_name", sa.String(100), nullable=False),
        sa.Column("conf", sa.Float(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["detection_records.id"],
            name="fk_detection_details_record",
            ondelete="CASCADE",
        ),
        **_TABLE_KW,
    )
    op.create_index("ix_detdetail_record", "detection_details", ["record_id"])

    # ===== feedbacks =====
    op.create_table(
        "feedbacks",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("user_id", _FK, nullable=False),
        sa.Column("type", sa.Enum("question", "result_verdict", name="feedback_type"), nullable=False),
        sa.Column("record_id", _FK, nullable=True),
        sa.Column("verdict", sa.Enum("correct", "wrong", "unsure", name="verdict"), nullable=True),
        sa.Column("correct_disease", sa.String(100), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "replied", "closed", name="feedback_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("last_reply_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW_UPDATE),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_feedbacks_user"),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["detection_records.id"],
            name="fk_feedbacks_record",
            ondelete="SET NULL",
        ),
        **_TABLE_KW,
    )
    op.create_index("ix_feedback_user", "feedbacks", ["user_id"])
    op.create_index("ix_feedback_type", "feedbacks", ["type"])
    op.create_index("ix_feedback_record", "feedbacks", ["record_id"])
    op.create_index("ix_feedback_status", "feedbacks", ["status"])
    op.create_index("ix_feedback_created", "feedbacks", ["created_at"])

    # ===== feedback_messages =====
    op.create_table(
        "feedback_messages",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("feedback_id", _FK, nullable=False),
        sa.Column("sender_role", sa.Enum("user", "admin", name="sender_role"), nullable=False),
        sa.Column("sender_id", _FK, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_read", _BOOL, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["feedbacks.id"],
            name="fk_feedback_messages_feedback",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], name="fk_feedback_messages_sender"),
        **_TABLE_KW,
    )
    op.create_index("ix_fbmsg_feedback", "feedback_messages", ["feedback_id"])
    op.create_index("ix_fbmsg_read", "feedback_messages", ["is_read"])
    op.create_index("ix_fbmsg_created", "feedback_messages", ["created_at"])

    # ===== disease_weather_rules =====
    op.create_table(
        "disease_weather_rules",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("disease", sa.String(100), nullable=False),
        sa.Column("crop", sa.String(50), nullable=True),
        sa.Column("temp_min", sa.Float(), nullable=True),
        sa.Column("temp_max", sa.Float(), nullable=True),
        sa.Column("humidity_min", sa.Float(), nullable=True),
        sa.Column("humidity_max", sa.Float(), nullable=True),
        sa.Column(
            "rain_condition",
            sa.Enum("any", "rain", "no_rain", name="rain_condition"),
            nullable=False,
            server_default="any",
        ),
        sa.Column("risk_level", sa.Enum("high", "mid", "low", name="risk_level"), nullable=False),
        sa.Column("advice", sa.String(500), nullable=True),
        sa.Column("enabled", _BOOL, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW_UPDATE),
        sa.PrimaryKeyConstraint("id"),
        **_TABLE_KW,
    )
    op.create_index("ix_rule_disease", "disease_weather_rules", ["disease"])
    op.create_index("ix_rule_enabled", "disease_weather_rules", ["enabled"])

    # ===== alert_records =====
    op.create_table(
        "alert_records",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column(
            "source",
            sa.Enum("weather", "detection", name="alert_source"),
            nullable=False,
            server_default="weather",
        ),
        sa.Column("disease", sa.String(100), nullable=False),
        sa.Column("risk_level", sa.Enum("high", "mid", "low", name="risk_level"), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("user_id", _FK, nullable=True),
        sa.Column("location", sa.String(50), nullable=True),
        sa.Column("forecast_date", sa.Date(), nullable=True),
        sa.Column("is_read", _BOOL, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_alert_records_user"),
        **_TABLE_KW,
    )
    op.create_index("ix_alert_source", "alert_records", ["source"])
    op.create_index("ix_alert_disease", "alert_records", ["disease"])
    op.create_index("ix_alert_risk", "alert_records", ["risk_level"])
    op.create_index("ix_alert_user", "alert_records", ["user_id"])
    op.create_index("ix_alert_read", "alert_records", ["is_read"])
    op.create_index("ix_alert_created", "alert_records", ["created_at"])

    # ===== knowledge_docs =====
    op.create_table(
        "knowledge_docs",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("crop", sa.String(50), nullable=True),
        sa.Column("disease", sa.String(100), nullable=True),
        sa.Column("source_path", sa.String(255), nullable=True),
        sa.Column("content_md", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "vector_status",
            sa.Enum("pending", "done", "failed", name="vector_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW_UPDATE),
        sa.PrimaryKeyConstraint("id"),
        **_TABLE_KW,
    )
    op.create_index("ix_kdoc_crop", "knowledge_docs", ["crop"])
    op.create_index("ix_kdoc_disease", "knowledge_docs", ["disease"])
    op.create_index("ix_kdoc_vector", "knowledge_docs", ["vector_status"])

    # ===== chat_sessions =====
    op.create_table(
        "chat_sessions",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("user_id", _FK, nullable=False),
        sa.Column("title", sa.String(100), nullable=True),
        sa.Column("detection_id", _FK, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW_UPDATE),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_chat_sessions_user"),
        sa.ForeignKeyConstraint(
            ["detection_id"],
            ["detection_records.id"],
            name="fk_chat_sessions_detection",
            ondelete="SET NULL",
        ),
        **_TABLE_KW,
    )
    op.create_index("ix_chat_user", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_detection", "chat_sessions", ["detection_id"])
    op.create_index("ix_chat_created", "chat_sessions", ["created_at"])

    # ===== chat_messages =====
    op.create_table(
        "chat_messages",
        sa.Column("id", _PK, autoincrement=True, nullable=False),
        sa.Column("chat_session_id", _FK, nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", name="chat_role"), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_sessions.id"],
            name="fk_chat_messages_session",
            ondelete="CASCADE",
        ),
        **_TABLE_KW,
    )
    op.create_index("ix_chatmsg_session", "chat_messages", ["chat_session_id"])
    op.create_index("ix_chatmsg_created", "chat_messages", ["created_at"])


def downgrade() -> None:
    """逆序删除全部业务表。"""
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("knowledge_docs")
    op.drop_table("alert_records")
    op.drop_table("disease_weather_rules")
    op.drop_table("feedback_messages")
    op.drop_table("feedbacks")
    op.drop_table("detection_details")
    op.drop_table("detection_records")
    op.drop_table("users")
