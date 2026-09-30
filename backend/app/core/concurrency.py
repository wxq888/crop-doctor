# -*- coding: utf-8 -*-
"""统一线程池：CPU 密集任务（模型推理）限流执行。

设计要点（见设计文档 §1 线程池与并发结论）：
- 暴露一个 ``ThreadPoolExecutor(max_workers=2)``，硬性限制并发推理数，保护 CPU。
- ``run_in_pool`` 把同步 ``fn`` 投递到该线程池并 await 结果，事件循环不被阻塞。
- 线程池**惰性创建、可重建**：``shutdown_pool()`` 关闭并置空，下一次
  ``run_in_pool`` 会重新创建，避免"应用关闭后再也无法调度"的问题
  （测试中多次建/拆 TestClient 会触发该场景）。

注：此处用事件循环自带的 ``run_in_executor`` 绑定自有线程池，以真正落实
``max_workers=2`` 的背压（``anyio`` 默认线程池上限为 40，无法满足限流意图）。
"""
import asyncio
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, TypeVar

T = TypeVar("T")

_MAX_WORKERS = 2

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def get_pool() -> ThreadPoolExecutor:
    """返回共享线程池；若已被关闭则重新创建。"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(
                    max_workers=_MAX_WORKERS,
                    thread_name_prefix="cropdoctor-pool",
                )
    return _pool


async def run_in_pool(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """把同步函数 ``fn`` 提交到共享线程池执行并等待结果。

    Args:
        fn: 同步可调用对象（如 ``detector.infer``）。
        *args: 位置参数。
        **kwargs: 关键字参数（用 ``functools.partial`` 包装以兼容 executor）。

    Returns:
        ``fn`` 的返回值。
    """
    loop = asyncio.get_running_loop()
    if args or kwargs:
        call: Callable[[], T] = partial(fn, *args, **kwargs)
    else:
        call = fn  # type: ignore[assignment]
    return await loop.run_in_executor(get_pool(), call)


def shutdown_pool() -> None:
    """关闭线程池（应用关闭时调用）；下次 ``run_in_pool`` 会自动重建。"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


def tune_torch_threads() -> None:
    """限制 torch 线程数，避免与线程池争抢 CPU。

    torch 未安装或初始化失败时静默跳过，不影响应用启动。
    """
    try:
        import torch

        torch.set_num_threads(min(4, os.cpu_count() or 2))
    except Exception:  # noqa: BLE001 —— 可选依赖，失败不影响启动
        pass


__all__ = ["get_pool", "run_in_pool", "shutdown_pool", "tune_torch_threads"]
