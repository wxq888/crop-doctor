# -*- coding: utf-8 -*-
"""admin 管理端接口：统计 / 全局检测记录 / 用户 / 模型。

设计依据：``docs/impl-pc-admin-v1.md`` §2.1。

红线：
- 全部端点要求 ``get_current_admin``（普通用户 → 403 / 1004）；
- 统计 / 趋势**全部为 SQL 聚合**，不触发任何 LLM 调用（Moonshot 账号 RPM=3，绝不可被打）；
- admin 可查任意用户的检测记录——这是与 detection 模块「数据隔离红线」**唯一**的合法越权入口；
- 指标命名遵循 team-lead 裁决 #1：只用「平均置信度」与「健康率」，**不得出现"准确率"**。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.core.exceptions import (
    CODE_RECORD_NOT_FOUND,
    BusinessError,
    ModelUnavailableError,
    UserNotFoundError,
    UserOpForbiddenError,
)
from app.core.response import ok, page_data
from app.core.security import hash_password
from app.models.detection import DetectionRecord
from app.models.feedback import Feedback
from app.models.user import User
from app.models.warning import AlertRecord
from app.schemas.admin import (
    AdminDetectionDetail,
    AdminDetectionItem,
    AdminUserDetail,
    AdminUserItem,
    ModelActivateIn,
    ModelInfo,
    ModelListOut,
    ResetPasswordIn,
    StatsOverview,
    StatsTrend,
    UserStatusIn,
)
from app.schemas.detection import DetBox, DetectionDetailOut
from app.services import model_registry, severity, yolo_infer
from app.services.classmap import crop_cn_by_en, crop_cn_of, disease_cn_of
from app.utils import storage

router = APIRouter()


# ============================================================
# 内部工具
# ============================================================
def _utcnow_naive() -> datetime:
    """当前 UTC 时间（naive，与 DB 存储口径一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clamp_days(days: int) -> int:
    """把 ``days`` 收敛到 1~30。"""
    return max(1, min(int(days), 30))


def _date_key(value: object) -> str:
    """把 ``func.date()`` 的返回值（MySQL=date / SQLite=str）规整为 ``YYYY-MM-DD``。"""
    return str(value)[:10]


def _model_info(path, active_name: str) -> ModelInfo:
    """由权重文件路径构造 :class:`ModelInfo`。"""
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(tzinfo=None)
    return ModelInfo(
        filename=path.name,
        size_mb=round(stat.st_size / 1024 / 1024, 2),
        modified_at=modified,
        is_active=(path.name == active_name),
    )


# ============================================================
# 端点：统计概览 / 趋势
# ============================================================
@router.get("/stats/overview", summary="管理端概览统计")
def stats_overview(
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """大屏顶部统计（今日检测 / 健康率 / 平均置信度 / 预警中 / 待回复工单等）。"""
    now = _utcnow_naive()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = now - timedelta(hours=24)

    today_detections = (
        db.scalar(
            select(func.count())
            .select_from(DetectionRecord)
            .where(DetectionRecord.created_at >= today_start)
        )
        or 0
    )
    total_detections = db.scalar(select(func.count()).select_from(DetectionRecord)) or 0
    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    today_new_users = (
        db.scalar(
            select(func.count()).select_from(User).where(User.created_at >= today_start)
        )
        or 0
    )
    today_healthy = (
        db.scalar(
            select(func.count())
            .select_from(DetectionRecord)
            .where(
                DetectionRecord.created_at >= today_start,
                DetectionRecord.severity_level == 0,
            )
        )
        or 0
    )
    avg_conf = db.scalar(
        select(func.avg(DetectionRecord.top_conf)).where(
            DetectionRecord.created_at >= today_start,
            DetectionRecord.top_conf.is_not(None),
        )
    )
    warnings_active = (
        db.scalar(
            select(func.count())
            .select_from(AlertRecord)
            .where(AlertRecord.created_at >= since_24h)
        )
        or 0
    )
    pending_feedbacks = (
        db.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.status == "pending")
        )
        or 0
    )

    healthy_rate = round(float(today_healthy) / float(today_detections), 4) if today_detections else 0.0
    data = StatsOverview(
        today_detections=int(today_detections),
        today_new_users=int(today_new_users),
        total_users=int(total_users),
        total_detections=int(total_detections),
        today_healthy_rate=healthy_rate,
        today_avg_conf=round(float(avg_conf), 4) if avg_conf is not None else 0.0,
        warnings_active=int(warnings_active),
        pending_feedbacks=int(pending_feedbacks),
    )
    return ok(data)


@router.get("/stats/trend", summary="管理端趋势 / 排行 / 分布")
def stats_trend(
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=30, description="统计天数")] = 7,
) -> dict:
    """近 N 日（UTC 日期）检测量 / 健康数 / 预警数 + 病害排行 + 严重度分布 + 按作物。"""
    n = _clamp_days(days)
    today = _utcnow_naive().date()
    date_list = [today - timedelta(days=(n - 1 - i)) for i in range(n)]
    day_keys = [d.strftime("%Y-%m-%d") for d in date_list]
    start_dt = datetime.combine(date_list[0], time.min)

    det_rows = db.execute(
        select(func.date(DetectionRecord.created_at), func.count())
        .where(DetectionRecord.created_at >= start_dt)
        .group_by(func.date(DetectionRecord.created_at))
    ).all()
    det_map = {_date_key(r[0]): int(r[1]) for r in det_rows}

    healthy_rows = db.execute(
        select(func.date(DetectionRecord.created_at), func.count())
        .where(
            DetectionRecord.created_at >= start_dt,
            DetectionRecord.severity_level == 0,
        )
        .group_by(func.date(DetectionRecord.created_at))
    ).all()
    healthy_map = {_date_key(r[0]): int(r[1]) for r in healthy_rows}

    warn_rows = db.execute(
        select(func.date(AlertRecord.created_at), func.count())
        .where(AlertRecord.created_at >= start_dt)
        .group_by(func.date(AlertRecord.created_at))
    ).all()
    warn_map = {_date_key(r[0]): int(r[1]) for r in warn_rows}

    rank_rows = db.execute(
        select(DetectionRecord.top_disease, func.count().label("c"))
        .where(
            DetectionRecord.created_at >= start_dt,
            DetectionRecord.top_disease.is_not(None),
        )
        .group_by(DetectionRecord.top_disease)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    disease_rank = [
        {"disease": r[0], "disease_cn": disease_cn_of(r[0]), "count": int(r[1])}
        for r in rank_rows
    ]

    sev_rows = db.execute(
        select(DetectionRecord.severity_level, func.count())
        .where(DetectionRecord.created_at >= start_dt)
        .group_by(DetectionRecord.severity_level)
    ).all()
    sev_map = {int(r[0]): int(r[1]) for r in sev_rows}
    severity_dist = [
        {"level": lv, "label": severity.label_of(lv), "count": sev_map.get(lv, 0)}
        for lv in range(4)
    ]

    crop_rows = db.execute(
        select(DetectionRecord.crop, func.count())
        .where(DetectionRecord.created_at >= start_dt, DetectionRecord.crop.is_not(None))
        .group_by(DetectionRecord.crop)
        .order_by(func.count().desc())
    ).all()
    by_crop = [
        {"crop": r[0], "crop_cn": crop_cn_by_en(r[0]), "count": int(r[1])}
        for r in crop_rows
    ]

    data = StatsTrend(
        days=day_keys,
        detections=[det_map.get(k, 0) for k in day_keys],
        healthy=[healthy_map.get(k, 0) for k in day_keys],
        warnings=[warn_map.get(k, 0) for k in day_keys],
        disease_rank=disease_rank,
        severity_dist=severity_dist,
        by_crop=by_crop,
    )
    return ok(data)


# ============================================================
# 端点：全局检测记录
# ============================================================
@router.get("/detections", summary="全局检测记录列表")
def list_detections(
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    user_id: Annotated[int | None, Query(description="按用户筛选")] = None,
    disease: Annotated[str | None, Query(max_length=100)] = None,
    severity_level: Annotated[int | None, Query(ge=0, le=3)] = None,
    crop: Annotated[str | None, Query(max_length=50)] = None,
    start: Annotated[datetime | None, Query(description="起始时间（UTC）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（UTC）")] = None,
    has_feedback: Annotated[bool | None, Query(description="是否存在关联工单")] = None,
) -> dict:
    """分页返回**全局**检测记录（admin 越权查全量，含用户名与反馈状态）。"""
    conditions = []
    if user_id is not None:
        conditions.append(DetectionRecord.user_id == user_id)
    if disease:
        conditions.append(DetectionRecord.top_disease == disease)
    if severity_level is not None:
        conditions.append(DetectionRecord.severity_level == severity_level)
    if crop:
        conditions.append(DetectionRecord.crop == crop)
    if start is not None:
        conditions.append(DetectionRecord.created_at >= start)
    if end is not None:
        conditions.append(DetectionRecord.created_at <= end)

    feedback_subq = select(Feedback.record_id).where(Feedback.record_id.is_not(None))
    if has_feedback is True:
        conditions.append(DetectionRecord.id.in_(feedback_subq))
    elif has_feedback is False:
        conditions.append(DetectionRecord.id.not_in(feedback_subq))

    total = db.scalar(select(func.count()).select_from(DetectionRecord).where(*conditions)) or 0
    rows = db.scalars(
        select(DetectionRecord)
        .where(*conditions)
        .order_by(DetectionRecord.created_at.desc(), DetectionRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    record_ids = [r.id for r in rows]
    user_ids = {r.user_id for r in rows}
    user_map: dict[int, str] = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            user_map[u.id] = u.username

    fb_status: dict[int, str] = {}
    if record_ids:
        for fb in db.scalars(select(Feedback).where(Feedback.record_id.in_(record_ids))).all():
            fb_status.setdefault(fb.record_id, fb.status)

    items = [
        AdminDetectionItem(
            id=r.id,
            thumb_url=storage.url_of(r.image_path),
            top_disease=r.top_disease,
            disease_cn=disease_cn_of(r.top_disease),
            crop=r.crop,
            crop_cn=crop_cn_of(r.top_disease),
            severity_level=r.severity_level,
            severity_label=severity.label_of(r.severity_level),
            top_conf=r.top_conf,
            user_id=r.user_id,
            username=user_map.get(r.user_id),
            feedback_status=fb_status.get(r.id),
            created_at=r.created_at,
        ).model_dump()
        for r in rows
    ]
    return ok(page_data(items, int(total), page, page_size))


@router.get("/detections/{record_id}", summary="全局检测记录详情")
def get_detection_detail(
    record_id: int,
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回任意用户的检测记录详情（唯一合法越权入口）；不存在 → 404 / 2004。"""
    record = db.get(DetectionRecord, record_id)
    if record is None:
        raise BusinessError(CODE_RECORD_NOT_FOUND, "检测记录不存在", http_status=404)
    username = None
    owner = db.get(User, record.user_id)
    if owner is not None:
        username = owner.username

    details = [DetBox(class_name=d.class_name, conf=d.conf, bbox=list(d.bbox)) for d in record.details]
    out = AdminDetectionDetail(
        id=record.id,
        severity_level=record.severity_level,
        severity_label=severity.label_of(record.severity_level),
        top_disease=record.top_disease,
        top_conf=record.top_conf,
        spot_count=record.spot_count,
        area_ratio=record.area_ratio,
        image_url=storage.url_of(record.image_path),
        annotated_url=storage.url_of(record.annotated_path),
        gradcam_status=record.gradcam_status,
        details=details,
        created_at=record.created_at,
        gradcam_url=storage.url_of(record.gradcam_path),
        crop=record.crop,
        location=record.location,
        user_id=record.user_id,
        username=username,
        disease_cn=disease_cn_of(record.top_disease),
        crop_cn=crop_cn_of(record.top_disease),
    )
    return ok(out)


# ============================================================
# 端点：用户管理
# ============================================================
def _counts_by_user(db: Session, user_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    """批量统计一组用户的检测数 / 反馈数。"""
    if not user_ids:
        return {}, {}
    det = dict(
        db.execute(
            select(DetectionRecord.user_id, func.count())
            .where(DetectionRecord.user_id.in_(user_ids))
            .group_by(DetectionRecord.user_id)
        ).all()
    )
    fb = dict(
        db.execute(
            select(Feedback.user_id, func.count())
            .where(Feedback.user_id.in_(user_ids))
            .group_by(Feedback.user_id)
        ).all()
    )
    return det, fb


@router.get("/users", summary="用户列表")
def list_users(
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    keyword: Annotated[str | None, Query(max_length=50, description="用户名/昵称模糊匹配")] = None,
    role: Annotated[str | None, Query(pattern="^(user|admin)$")] = None,
    status: Annotated[int | None, Query(ge=0, le=1)] = None,
) -> dict:
    """分页返回用户列表（含检测数 / 反馈数）。"""
    conditions = []
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(User.username.like(like), User.nickname.like(like)))
    if role:
        conditions.append(User.role == role)
    if status is not None:
        conditions.append(User.status == status)

    total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    rows = db.scalars(
        select(User)
        .where(*conditions)
        .order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    user_ids = [u.id for u in rows]
    det_counts, fb_counts = _counts_by_user(db, user_ids)

    items = [
        AdminUserItem(
            id=u.id,
            username=u.username,
            nickname=u.nickname,
            role=u.role,
            status=u.status,
            created_at=u.created_at,
            detection_count=int(det_counts.get(u.id, 0)),
            feedback_count=int(fb_counts.get(u.id, 0)),
        ).model_dump()
        for u in rows
    ]
    return ok(page_data(items, int(total), page, page_size))


@router.get("/users/{user_id}", summary="用户详情")
def get_user_detail(
    user_id: int,
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回用户详情（含检测 / 反馈 / 预警计数）；不存在 → 404 / 8001。"""
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError()
    detection_count = (
        db.scalar(
            select(func.count())
            .select_from(DetectionRecord)
            .where(DetectionRecord.user_id == user.id)
        )
        or 0
    )
    feedback_count = (
        db.scalar(select(func.count()).select_from(Feedback).where(Feedback.user_id == user.id))
        or 0
    )
    warning_count = (
        db.scalar(select(func.count()).select_from(AlertRecord).where(AlertRecord.user_id == user.id))
        or 0
    )
    out = AdminUserDetail(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        detection_count=int(detection_count),
        feedback_count=int(feedback_count),
        avatar=user.avatar,
        phone=user.phone,
        warning_count=int(warning_count),
    )
    return ok(out)


@router.put("/users/{user_id}/status", summary="启用 / 禁用用户")
def set_user_status(
    user_id: int,
    payload: UserStatusIn,
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """启用/禁用用户；禁自己或禁用最后一个启用中的管理员 → 409 / 8002。"""
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError()

    if payload.status == 0:
        if user.id == current_admin.id:
            raise UserOpForbiddenError("不能禁用当前登录的管理员账号")
        if user.role == "admin":
            active_admins = (
                db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == "admin", User.status == 1)
                )
                or 0
            )
            if active_admins <= 1:
                raise UserOpForbiddenError("不能禁用最后一个启用中的管理员")

    user.status = payload.status
    db.commit()
    db.refresh(user)

    detection_count = (
        db.scalar(
            select(func.count())
            .select_from(DetectionRecord)
            .where(DetectionRecord.user_id == user.id)
        )
        or 0
    )
    feedback_count = (
        db.scalar(select(func.count()).select_from(Feedback).where(Feedback.user_id == user.id))
        or 0
    )
    return ok(
        AdminUserItem(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            detection_count=int(detection_count),
            feedback_count=int(feedback_count),
        )
    )


@router.post("/users/{user_id}/reset-password", summary="重置用户密码")
def reset_user_password(
    user_id: int,
    payload: ResetPasswordIn,
    current_admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """重置密码（未传 ``new_password`` 则生成强随机密码）；不存在 → 404 / 8001。"""
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError()

    new_password = (payload.new_password or "").strip() or _gen_password()
    user.password_hash = hash_password(new_password)
    db.commit()
    return ok({"username": user.username, "new_password": new_password})


def _gen_password(length: int = 12) -> str:
    """生成强随机密码（字母 + 数字 + 少量符号）。"""
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(max(6, length)))


# ============================================================
# 端点：模型管理
# ============================================================
@router.get("/model", summary="模型权重列表")
def list_models(
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """列出 ``ml/exports`` 权重版本 + 当前生效项 + 加载状态。"""
    active = model_registry.active_model_name()
    items = [_model_info(p, active) for p in model_registry.list_weight_files()]
    out = ModelListOut(items=items, active=active, loaded=yolo_infer.is_loaded())
    return ok(out)


@router.post("/model/activate", summary="热切换生效模型")
def activate_model(
    payload: ModelActivateIn,
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """热切换 YOLO 权重（CPU 重载，数秒）；持久化到 ``active_model.json`` 供重启生效。

    文件不存在 / 后缀不合法 → 400 / 8003。
    """
    filename = payload.filename.strip()
    target = model_registry.exports_dir() / filename
    if not target.exists() or target.suffix.lower() not in (".pt", ".pth"):
        raise ModelUnavailableError(f"模型文件不存在或不可用：{filename}")

    model_registry.reload_detector(filename)
    model_registry.persist_active_model(filename)
    return ok(_model_info(target, filename))
