# -*- coding: utf-8 -*-
"""检测接口：图片检测 / 记录列表 / 记录详情 / 热力图 / 删除 / WS 实时检测。

数据隔离红线：本模块所有查询/删除在 SQL 层强制 ``user_id == current_user.id``；
越权访问统一返回 2004（不区分"不存在"与"无权"，防探测）。

WS 实时检测（``WS /detection/ws/realtime``，docs/impl-backend-v1.md §5.2）：
H5 前端 getUserMedia 抓帧（2~5fps）→ WebSocket 二进制帧 → 服务端 YOLO 推理 →
回 JSON 检测框 → 前端叠加画框。**瞬态通道：不写数据库、不落盘**。
"""
import asyncio
import contextlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import (
    CODE_IMAGE_TOO_LARGE,
    CODE_NO_DETECTION,
    CODE_RECORD_NOT_FOUND,
    CODE_UNSUPPORTED_IMAGE,
    BusinessError,
    InferenceError,
    ModelLoadError,
)
from app.core.response import ok, page_data
from app.core.security import decode_access_token
from app.models.detection import DetectionDetail, DetectionRecord
from app.models.user import User
from app.schemas.detection import (
    DetBox,
    DetectionDetailOut,
    DetectionListItem,
    DetectionRecordOut,
    GradCamStatusOut,
)
from app.services import severity, yolo_infer
from app.services.classmap import crop_cn_of, disease_cn_of, row_of
from app.services.gradcam import run_gradcam_job
from app.services.monitor import _emit_detection_event
from app.utils import storage
from app.utils.image import bytes_to_ndarray, imwrite_cn

router = APIRouter()


def _derive_crop(label: str | None) -> str | None:
    """由 ``top_disease`` 前缀派生作物名（如 ``Apple___Apple_scab`` → ``Apple``）。"""
    if not label:
        return None
    return label.split("___")[0] if "___" in label else label.split("_")[0]


def _is_healthy_class(label: str | None) -> bool:
    """类名是否健康类（以 ``kb/class-map.json`` 的 ``doc_type`` 为单一事实来源）。"""
    return row_of(label).get("doc_type") == "healthy"


def _cn_out_fields(top_disease: str | None) -> dict:
    """由 class-map 派生 REST 出参的中文字段（缺失时回退原始类名）。"""
    return {
        "disease_cn": disease_cn_of(top_disease),
        "crop_cn": crop_cn_of(top_disease),
        "is_healthy": _is_healthy_class(top_disease),
    }


def _record_to_out(record: DetectionRecord) -> DetectionRecordOut:
    """ORM 记录 → 创建响应模型（含明细框）。"""
    details = [DetBox(class_name=d.class_name, conf=d.conf, bbox=list(d.bbox)) for d in record.details]
    return DetectionRecordOut(
        id=record.id,
        severity_level=record.severity_level,
        severity_label=severity.label_of(record.severity_level),
        top_disease=record.top_disease,
        top_conf=record.top_conf,
        **_cn_out_fields(record.top_disease),
        spot_count=record.spot_count,
        area_ratio=record.area_ratio,
        image_url=storage.url_of(record.image_path),
        annotated_url=storage.url_of(record.annotated_path),
        gradcam_status=record.gradcam_status,
        details=details,
        created_at=record.created_at,
    )


@router.post("/image", summary="上传图片进行病害检测")
async def detect_image(
    file: Annotated[UploadFile, File(description="待检测图片文件")],
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    location: Annotated[str | None, Form(max_length=50, description="检测地定位")] = None,
    conf: Annotated[float | None, Form(ge=0.0, le=1.0, description="置信度阈值")] = None,
) -> dict:
    """读取图片 → YOLO 推理 → 分级 → 落盘 → 写库 → 后台生成热力图 → 返回结果。"""
    # 1) 格式校验（先做便宜的检查）
    filename = file.filename or "upload.jpg"
    ext = Path(filename).suffix.lower()
    if ext not in storage.ALLOWED_EXTENSIONS or file.content_type not in storage.ALLOWED_CONTENT_TYPES:
        raise BusinessError(CODE_UNSUPPORTED_IMAGE, "图片格式不支持，仅支持 jpg/png/webp", http_status=400)

    # 2) 大小校验
    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise BusinessError(
            CODE_IMAGE_TOO_LARGE,
            f"图片过大，最大 {settings.max_upload_mb}MB",
            http_status=413,
        )

    # 3) 解码
    image = bytes_to_ndarray(data)
    if image is None:
        raise BusinessError(CODE_UNSUPPORTED_IMAGE, "图片解析失败，请上传有效图片", http_status=400)

    # 4) 推理 + 分级
    result = await yolo_infer.infer_async(image, conf)
    if result.spot_count <= 0:
        raise BusinessError(CODE_NO_DETECTION, "未检出叶片或病害目标，请重拍", http_status=422)

    level = severity.grade(result.spot_count, result.area_ratio)
    spot_count = result.spot_count
    area_ratio = result.area_ratio
    # 健康类豁免：Grad-CAM 对健康叶整叶高亮 → 病斑数/面积占比无意义，统一置零；
    # 定级固定为 0（词表「无」，前端按 is_healthy 展示映射为「健康」）。
    # 判定以 kb/class-map.json 的 doc_type 为单一事实来源，不做字符串硬判。
    if _is_healthy_class(result.top_label):
        level = 0
        spot_count = 0
        area_ratio = 0.0
    crop = _derive_crop(result.top_label)

    # 5) 落盘（原图 + 标注图）
    storage.ensure_dirs()
    img_name = storage.gen_filename(filename)
    ann_name = storage.gen_filename(".jpg")
    img_rel = storage.rel_path(storage.IMG_DIR, img_name)
    ann_rel = storage.rel_path(storage.ANN_DIR, ann_name)
    storage.abs_path(img_rel).write_bytes(data)
    if not imwrite_cn(str(storage.abs_path(ann_rel)), result.annotated_bgr):
        logger.warning(f"标注图落盘失败：{ann_rel}")

    # 6) 写库（头 + 明细）
    record = DetectionRecord(
        user_id=current_user.id,
        image_path=img_rel,
        annotated_path=ann_rel,
        severity_level=level,
        spot_count=spot_count,
        area_ratio=area_ratio,
        top_disease=result.top_label,
        top_conf=result.top_conf,
        crop=crop,
        location=location,
        gradcam_status="pending",
    )
    for box in result.boxes:
        record.details.append(
            DetectionDetail(class_name=box.label, conf=box.conf, bbox=list(box.bbox))
        )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 7) 后台异步生成 Grad-CAM（响应先返回）
    background_tasks.add_task(run_gradcam_job, record.id)

    # 8) monitor 事件发射：检测完成后推 detection.created（设计文档 §3.2，仅此 1 行钩子，不改其它逻辑）
    background_tasks.add_task(_emit_detection_event, record.id, current_user.id)

    return ok(_record_to_out(record))


@router.get("/records", summary="我的检测记录列表")
def list_records(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 10,
    disease: Annotated[str | None, Query(max_length=100, description="按病害名筛选")] = None,
    severity_level: Annotated[int | None, Query(ge=0, le=3, description="按严重度筛选")] = None,
    crop: Annotated[str | None, Query(max_length=50, description="按作物筛选")] = None,
    start: Annotated[datetime | None, Query(description="起始时间（UTC）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（UTC）")] = None,
) -> dict:
    """分页返回当前用户本人的检测记录（强制 user_id 过滤）。"""
    conditions = [DetectionRecord.user_id == current_user.id]
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

    total = db.scalar(select(func.count()).select_from(DetectionRecord).where(*conditions)) or 0
    rows = db.scalars(
        select(DetectionRecord)
        .where(*conditions)
        .order_by(DetectionRecord.created_at.desc(), DetectionRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        DetectionListItem(
            id=r.id,
            thumb_url=storage.url_of(r.image_path),
            top_disease=r.top_disease,
            severity_level=r.severity_level,
            severity_label=severity.label_of(r.severity_level),
            disease_cn=disease_cn_of(r.top_disease),
            is_healthy=_is_healthy_class(r.top_disease),
            created_at=r.created_at,
        ).model_dump()
        for r in rows
    ]
    return ok(page_data(items, int(total), page, page_size))


def _get_owned_record(db: Session, record_id: int, user_id: int) -> DetectionRecord:
    """按 id + user_id 取记录；不存在或非本人一律抛 2004。"""
    record = db.scalar(
        select(DetectionRecord).where(
            DetectionRecord.id == record_id,
            DetectionRecord.user_id == user_id,
        )
    )
    if record is None:
        raise BusinessError(CODE_RECORD_NOT_FOUND, "检测记录不存在或无权访问", http_status=404)
    return record


@router.get("/records/{record_id}", summary="检测记录详情")
def get_record_detail(
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回本人某条检测记录的详情。"""
    record = _get_owned_record(db, record_id, current_user.id)
    details = [DetBox(class_name=d.class_name, conf=d.conf, bbox=list(d.bbox)) for d in record.details]
    out = DetectionDetailOut(
        id=record.id,
        severity_level=record.severity_level,
        severity_label=severity.label_of(record.severity_level),
        top_disease=record.top_disease,
        top_conf=record.top_conf,
        **_cn_out_fields(record.top_disease),
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
    )
    return ok(out)


@router.get("/records/{record_id}/gradcam", summary="查询热力图状态")
def get_record_gradcam(
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回热力图异步生成状态与 URL（未完成时 url 为 null）。"""
    record = _get_owned_record(db, record_id, current_user.id)
    return ok(
        GradCamStatusOut(
            status=record.gradcam_status,
            url=storage.url_of(record.gradcam_path) if record.gradcam_status == "done" else None,
        )
    )


@router.delete("/records/{record_id}", summary="删除检测记录")
def delete_record(
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """删除本人某条检测记录（明细级联删除，产物文件尽力清理）。"""
    record = _get_owned_record(db, record_id, current_user.id)
    for rel in (record.image_path, record.annotated_path, record.gradcam_path):
        if rel:
            try:
                storage.abs_path(rel).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"删除产物文件失败：{rel}（{exc}）")
    db.execute(delete(DetectionRecord).where(DetectionRecord.id == record.id))
    db.commit()
    return ok(None)


# ============================================================
# WS /detection/ws/realtime —— H5 摄像头实时检测（瞬态、不落库不落盘）
# 设计依据：docs/impl-backend-v1.md §5.2 + architecture.md §6 决策 4
# ============================================================

# WS 关闭码：鉴权语义对齐 monitor WS（4401）；超限/模型码为本端点独有
RT_CLOSE_UNAUTHORIZED = 4401  # 无 token / token 无效 / 用户被禁用
RT_CLOSE_OVERSIZED = 4403  # 单帧超过大小上限
RT_CLOSE_MODEL_UNREADY = 4503  # YOLO 模型未就绪

# 单帧大小上限：2.5fps 抓帧 JPEG(q0.7) 通常 < 200KB，1MB 已足够宽裕
RT_MAX_FRAME_BYTES = 1 * 1024 * 1024
# 默认置信度阈值（客户端可用首帧 config 消息覆盖）
RT_DEFAULT_CONF = 0.25

_JPEG_MAGIC = b"\xff\xd8"


def _rt_frame(frame_type: str, data: dict) -> str:
    """构造 JSON 信封文本帧（``{v,type,data}``，风格与 monitor WS 一致）。"""
    return json.dumps({"v": 1, "type": frame_type, "data": data}, ensure_ascii=False)


def _split_frame_payload(payload: bytes) -> tuple[int, bytes]:
    """二进制帧解包：约定前端在 JPEG 前加 **4 字节大端 frame_id** 前缀。

    兼容无前缀的原始 JPEG（以 ``0xFFD8`` 魔数识别），此时 ``frame_id=0``。
    """
    if len(payload) > 4 and not payload.startswith(_JPEG_MAGIC):
        return int.from_bytes(payload[:4], "big"), payload[4:]
    return 0, payload


def _resolve_ws_user(db: Session, token: str | None) -> User | None:
    """query token → 校验 JWT → 查 users → 校验 ``status==1``。

    与 monitor WS 的同名逻辑同源（任何已登录用户即可，**不要求 admin**）；
    任一环节失败返回 ``None``（握手方据此 close 4401），不抛异常。
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except Exception:  # noqa: BLE001 —— token 无效一律按未授权处理
        return None
    user = db.get(User, user_id)
    if user is None or user.status != 1:
        return None
    return user


async def _rt_send(websocket: WebSocket, raw: str) -> bool:
    """发送一条 JSON 文本帧；连接已断返回 False（由主循环负责收尾）。"""
    try:
        await websocket.send_text(raw)
        return True
    except Exception:  # noqa: BLE001 —— 发送失败即连接不可用
        return False


async def _rt_heartbeat_loop(websocket: WebSocket, interval: int) -> None:
    """服务端定时发 ``ping``；断开/取消时静默退出（对齐 monitor WS 心跳语义）。"""
    try:
        while True:
            await asyncio.sleep(interval)
            if not await _rt_send(websocket, _rt_frame("ping", {})):
                return
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001 —— 连接已断，主循环会清理
        return


async def _rt_process_frame(websocket: WebSocket, jpeg: bytes, frame_id: int, conf: float) -> None:
    """单帧处理：解码 → 线程池推理 → 回 ``frame.result``。

    帧级失败只回 ``error`` 帧不断连接（实时场景单帧失败可恢复）；
    模型级失败（ModelLoadError）同样回 error 帧，由调用方决定 close。
    """
    start = time.monotonic()
    image = bytes_to_ndarray(jpeg)
    if image is None:
        await _rt_send(websocket, _rt_frame("error", {"code": 9000, "message": "帧解码失败，请重新抓拍"}))
        return
    try:
        result = await yolo_infer.infer_async(image, conf)
    except InferenceError as exc:
        await _rt_send(websocket, _rt_frame("error", {"code": 9000, "message": str(exc)}))
        return
    except ModelLoadError:
        await _rt_send(
            websocket,
            _rt_frame("error", {"code": RT_CLOSE_MODEL_UNREADY, "message": "检测模型未就绪，请稍后重试"}),
        )
        return

    elapsed_ms = int((time.monotonic() - start) * 1000)
    boxes = [
        {
            "cls_id": b.cls_id,
            "label": b.label,
            "label_cn": disease_cn_of(b.label),
            "conf": round(b.conf, 4),
            "bbox": list(b.bbox),
        }
        for b in result.boxes
    ]
    await _rt_send(
        websocket,
        _rt_frame(
            "frame.result",
            {"frame_id": frame_id, "count": len(boxes), "boxes": boxes, "elapsed_ms": elapsed_ms},
        ),
    )


@router.websocket("/ws/realtime", name="detection-realtime")
async def ws_realtime(
    websocket: WebSocket,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """摄像头实时检测 WS：**先 accept** → query token 鉴权（任何已登录用户）→ 逐帧推理。

    网络层要点（与 monitor WS 同一坑）：Starlette 在 ``accept()`` 之前的
    ``close(4401)`` 会被翻译成 HTTP 403 握手拒绝，浏览器拿不到自定义 close
    code；必须先完成 101 握手再 close，前端才能按 4401/4403/4503 区分提示。

    背压设计：推理经线程池异步执行（CPU 单帧数百 ms）。上一帧 ``infer_task``
    未完成时到达的新二进制帧**直接丢弃**并回 ``frame.skipped``，绝不堆积排队。
    """
    await websocket.accept()

    user = _resolve_ws_user(db, websocket.query_params.get("token"))
    if user is None:
        await websocket.close(code=RT_CLOSE_UNAUTHORIZED)
        return

    if not yolo_infer.is_loaded():
        await _rt_send(
            websocket,
            _rt_frame("error", {"code": RT_CLOSE_MODEL_UNREADY, "message": "检测模型未就绪，请稍后重试"}),
        )
        await websocket.close(code=RT_CLOSE_MODEL_UNREADY)
        return

    conf = RT_DEFAULT_CONF
    infer_task: asyncio.Task | None = None
    heartbeat_task = asyncio.create_task(
        _rt_heartbeat_loop(websocket, max(5, int(settings.monitor_heartbeat_seconds))),
        name="realtime-heartbeat",
    )
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            # ---- 二进制帧：JPEG 实时帧（4 字节 frame_id 前缀 + JPEG）----
            payload = message.get("bytes")
            if payload is not None:
                frame_id, jpeg = _split_frame_payload(payload)
                if len(jpeg) > RT_MAX_FRAME_BYTES:
                    await _rt_send(
                        websocket,
                        _rt_frame("error", {"code": RT_CLOSE_OVERSIZED, "message": "单帧超过 1MB 上限"}),
                    )
                    await websocket.close(code=RT_CLOSE_OVERSIZED)
                    break
                if infer_task is not None and not infer_task.done():
                    # 背压：上一帧没算完 → 丢弃新帧并告知，绝不排队堆积
                    await _rt_send(websocket, _rt_frame("frame.skipped", {"frame_id": frame_id}))
                    continue
                infer_task = asyncio.create_task(_rt_process_frame(websocket, jpeg, frame_id, conf))
                continue

            # ---- 文本帧：config（置信度）/ 心跳 ----
            raw = message.get("text")
            try:
                frame = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                logger.debug("realtime WS 收到非 JSON 文本帧，已忽略")
                continue
            if not isinstance(frame, dict):
                continue
            kind = frame.get("type")
            if kind == "config":
                conf_val = frame.get("conf")
                if isinstance(conf_val, (int, float)) and 0.01 <= float(conf_val) <= 0.99:
                    conf = float(conf_val)
            elif kind == "ping":
                await _rt_send(websocket, _rt_frame("pong", {}))
            # pong / 未知帧：忽略（对齐 monitor WS）
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 —— 连接异常按断开处理
        logger.debug(f"realtime WS 异常关闭：{type(exc).__name__}: {exc}")
    finally:
        heartbeat_task.cancel()
        if infer_task is not None:
            infer_task.cancel()
            with contextlib.suppress(BaseException):
                await infer_task
        with contextlib.suppress(BaseException):
            await heartbeat_task
