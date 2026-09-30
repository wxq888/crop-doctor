# -*- coding: utf-8 -*-
"""Redis 异步客户端（共享连接池）。

供天气缓存等场景使用；连接失败由调用方降级处理，不在此处抛业务异常。
"""
import redis.asyncio as aioredis

from app.core.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """返回共享的 ``redis.asyncio.Redis`` 客户端（懒初始化）。"""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """关闭 Redis 连接（应用关闭时调用）。"""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def ping() -> bool:
    """探活：成功返回 True，任何异常返回 False（不抛出）。"""
    try:
        return bool(await get_redis().ping())
    except Exception:  # noqa: BLE001 —— 探活失败不应影响主流程
        return False
