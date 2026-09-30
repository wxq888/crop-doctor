# -*- coding: utf-8 -*-
"""FastAPI 应用装配：CORS / 路由 / 异常 / 静态资源 / 生命周期。

启动流程：日志 → torch 线程数 → 上传目录 → YOLO 加载 → Redis 探活 → RAG 后台预热。
关闭流程：线程池 → Redis。
"""
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.concurrency import shutdown_pool, tune_torch_threads
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.logging import RequestLogMiddleware, setup_logging
from app.core.redis_client import close_redis
from app.core.redis_client import ping as redis_ping
from app.core.response import fail, ok
from app.services import model_registry, yolo_infer
from app.services.monitor import monitor_hub

# 确保上传目录与静态挂载点在 import 期即存在
for _sub in ("images", "annotated", "gradcam"):
    (settings.upload_path / _sub).mkdir(parents=True, exist_ok=True)


def _warmup_rag() -> None:
    """后台预热 RAG（bge 模型 + FAISS 索引），**不阻塞应用启动**。

    首字冷启动实测约 20s，故起一个守护线程在后台调用 ``rag_service.ensure_loaded()``，
    使模型在服务就绪后即完成加载，避免首个用户请求等待。任何失败仅记日志，绝不影响启动。
    """

    def _job() -> None:
        try:
            from app.services.rag import rag_service

            ready = rag_service.ensure_loaded()
            logger.info(f"RAG 后台预热{'完成' if ready else '降级（索引/模型不可用）'}")
        except Exception as exc:  # noqa: BLE001 —— 预热失败必须被吞掉，绝不影响启动
            logger.warning(f"RAG 后台预热失败（已忽略）：{type(exc).__name__}: {exc}")

    threading.Thread(target=_job, name="rag-warmup", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭钩子。"""
    setup_logging()
    logger.info(f"启动 CropDoctor 后端 | env={settings.app_env}")
    tune_torch_threads()

    # 模型热切换持久化：若存在 ml/exports/active_model.json 则回填生效权重（team-lead 裁决 #2）
    # —— 必须在 YOLO 加载之前应用，重启后仍生效（文件缺失则沿用 .env 的 YOLO_WEIGHTS_PATH）
    try:
        persisted = model_registry.active_model_name()
        settings.yolo_weights_path = str(model_registry.exports_dir() / persisted)
        logger.info(f"应用持久化生效权重：{persisted}")
    except Exception as exc:  # noqa: BLE001 —— 读取失败不影响启动，回退默认权重
        logger.warning(f"读取持久化生效权重失败（用 .env 默认权重）：{exc}")

    # YOLO 主链路：启动即加载（失败不阻断启动，健康检查可见）
    try:
        yolo_infer.detector.load()
        app.state.yolo = yolo_infer.detector
        logger.info(f"YOLO 权重加载完成：{settings.yolo_weights_abs}")
    except Exception as exc:  # noqa: BLE001 —— 加载失败不阻断启动
        app.state.yolo = None
        logger.error(f"YOLO 权重加载失败，检测接口将不可用：{exc}")

    if await redis_ping():
        logger.info("Redis 连接正常")
    else:
        logger.warning("Redis 连接失败（天气缓存将降级）")

    # monitor 事件总线：订阅 Redis Pub/Sub（失败自动降级为本地扇出，不阻断启动）
    try:
        await monitor_hub.start()
    except Exception as exc:  # noqa: BLE001 —— 订阅失败不影响应用启动
        logger.warning(f"monitor 事件总线启动失败（降级为本地扇出）：{exc}")

    # 预警定时刷新：条件导入 + 异常兜底挂载（模块未落地 / 启动失败均不影响应用）
    # —— 由 start_scheduler() 自行判断 WARNING_ENABLED 开关（false 时记日志并返回 None）
    try:
        from app.services.weather_risk import start_scheduler  # noqa: PLC0415 —— 条件导入

        start_scheduler()
    except Exception:  # noqa: BLE001 —— 调度失败绝不阻断启动
        logger.exception("预警定时调度启动失败（不影响主流程）")

    # RAG 后台预热：不阻塞启动，首个 chat 请求无需等 bge 冷加载
    _warmup_rag()

    yield

    # 关闭：先停 monitor 订阅，再回收线程池 / Redis
    try:
        await monitor_hub.stop()
    except Exception as exc:  # noqa: BLE001 —— 关闭失败不影响退出
        logger.warning(f"monitor 事件总线关闭异常（已忽略）：{exc}")
    shutdown_pool()
    await close_redis()
    logger.info("CropDoctor 后端已关闭")


app = FastAPI(
    title="作物医生 CropDoctor API",
    version="0.1.0",
    description="农作物病害智能检测与问诊平台后端（Phase 1）",
    lifespan=lifespan,
)

# CORS：开发期放开
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志
app.add_middleware(RequestLogMiddleware)

# 静态资源：上传产物（原图 / 标注图 / 热力图）
app.mount("/static", StaticFiles(directory=str(settings.upload_path)), name="static")

# 业务路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["系统"], summary="健康检查")
async def health() -> dict:
    """探活：返回服务状态、YOLO 加载状态、Redis 连通性。"""
    return ok(
        {
            "status": "ok",
            "env": settings.app_env,
            "yolo_loaded": yolo_infer.is_loaded(),
            "redis": await redis_ping(),
        }
    )


# ===== 全局异常处理器：统一 {code, message, data} 信封 =====
@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError) -> JSONResponse:
    """业务异常 → 统一信封。"""
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """参数校验失败 → 422（信封统一，业务码沿用 9000）。"""
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    detail = f"{loc}: {first.get('msg', '参数校验失败')}" if loc else "参数校验失败"
    return JSONResponse(status_code=422, content=fail(9000, detail))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """框架级 HTTP 异常（如未知路由）→ 统一信封。"""
    code = {401: 1003, 403: 1004}.get(exc.status_code, 9000)
    return JSONResponse(status_code=exc.status_code, content=fail(code, str(exc.detail)))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常 → 500 / 9000，并记录堆栈。"""
    logger.exception(f"未捕获异常：{request.method} {request.url.path}")
    return JSONResponse(status_code=500, content=fail(9000, "服务器内部错误"))
