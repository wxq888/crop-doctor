# -*- coding: utf-8 -*-
"""loguru 日志配置与请求日志中间件。

输出：stdout（彩色）+ ``backend/logs/app.log``（按天轮转，保留 7 天）。
并接管 ``uvicorn`` 与 ``sqlalchemy`` 的标准 logging 输出，避免双份日志格式。
"""
import logging
import sys
import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import REPO_ROOT

_LOG_DIR = REPO_ROOT / "backend" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)


class _InterceptHandler(logging.Handler):
    """把标准 logging 记录转发给 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # depth=6 让 loguru 定位到真正的调用点
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """初始化日志系统（应用启动时调用一次）。"""
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        enqueue=False,
        backtrace=False,
        diagnose=False,
        format=_CONSOLE_FORMAT,
    )
    logger.add(
        str(_LOG_DIR / "app.log"),
        level="INFO",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.INFO, force=True)

    # uvicorn 的逐请求日志由 RequestLogMiddleware 统一记录，这里只降噪不重复
    _noisy_loggers = {
        "uvicorn.access",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
    }
    for name in ("uvicorn", "uvicorn.error", "sqlalchemy.engine", *_noisy_loggers):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [_InterceptHandler()]
        std_logger.propagate = False
        if name in _noisy_loggers:
            std_logger.setLevel(logging.WARNING)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """请求日志中间件：记录 ``method path status cost_ms``。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """处理请求并记录耗时。"""
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            cost_ms = (time.perf_counter() - start) * 1000
            logger.exception(f"{request.method} {request.url.path} 500 {cost_ms:.1f}ms")
            raise
        cost_ms = (time.perf_counter() - start) * 1000
        logger.info(f"{request.method} {request.url.path} {response.status_code} {cost_ms:.1f}ms")
        return response


__all__ = ["setup_logging", "RequestLogMiddleware"]
