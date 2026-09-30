# -*- coding: utf-8 -*-
"""LLM 客户端（OpenAI 兼容协议，SSE 流式），未配 key 时降级。

设计依据：``docs/impl-rag-chat-v1.md`` §2.2 / §2.3。当前生产适配的是 **Moonshot/Kimi**
（``DEEPSEEK_BASE_URL=https://api.moonshot.cn/v1``、``LLM_MODEL=kimi-k2.6``；变量名为历史命名，沿用不改）。

Kimi（kimi-k2.6）三条硬约束（实测，务必遵守，否则 chat 会直接报错/空白）：
1. **temperature**：关闭思考时必须为 ``0.6``（其它值服务端直接拒绝：only 0.6 is allowed）；
2. **推理模型**：默认把答案藏在 ``reasoning_content``，思考可能吃光 token 导致 ``content`` 为空
   （``finish_reason=length``）→ 必须传 ``extra_body={"thinking": {"type": "disabled"}}`` **关闭思考**；
3. **限流**：该账号 ``max RPM = 3``（每分钟仅 3 次请求）→ 触发 ``429 RateLimitError`` 时
   **直接降级、绝不重试**（重试只会加剧 429）。

行为约定：
- 客户端 ``AsyncOpenAI``，``max_retries=0``（重试策略自行控制）；
- ``stream_chat`` 流式产出**增量文本 token**；
- 首包前连接类错误（超时/网络）重试 1 次，仍失败抛 ``LLMUnavailableError``；HTTP 状态错误（含 429）不重试；
- 429 → 抛 ``LLMRateLimitError``（``LLMUnavailableError`` 子类，带用户友好文案），由调用方转降级；
- 流式中途失败 → 抛 ``LLMStreamError``（调用方保留已产出文本）；
- 未配置 key → 抛 ``LLMUnavailableError``（调用方转降级文案，HTTP 依旧 200）。
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from loguru import logger
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from app.core.config import settings

# Kimi 关闭思考模式下唯一允许的 temperature
_KIMI_DISABLED_THINKING_TEMPERATURE = 0.6


class LLMError(Exception):
    """LLM 调用异常基类。"""


class LLMUnavailableError(LLMError):
    """未配置 key，或连接层失败（首包前）→ 调用方转降级文案。

    Args:
        message: 面向日志/诊断的技术信息。
        user_message: 面向用户的降级文案；非空时调用方优先用它（如 429 限流提示）。
    """

    def __init__(self, message: str, *, user_message: str | None = None) -> None:
        super().__init__(message)
        self.user_message: str | None = user_message


class LLMRateLimitError(LLMUnavailableError):
    """接口限流（HTTP 429）→ 直接降级、不重试。"""

    def __init__(self, message: str = "大模型接口请求过于频繁（429）") -> None:
        super().__init__(
            message,
            user_message="请求过于频繁，请稍后再试（当前大模型账号存在每分钟请求数限制）。",
        )


class LLMStreamError(LLMError):
    """流式中途失败 → 调用方发 SSE error 事件，并保留已产出文本。"""


@dataclass
class LLMChatResult:
    """非流式补全结果。"""

    text: str
    finish_reason: str | None
    elapsed_ms: int


def _llm_timeout_seconds() -> float:
    """LLM 超时秒数；键缺失时回退默认 60。"""
    try:
        return float(getattr(settings, "llm_timeout_seconds", 60))
    except (TypeError, ValueError):
        return 60.0


def _llm_max_tokens() -> int:
    """单次生成上限；键缺失时回退默认 2048（推理模型吃 token，且 RAG 上下文较长）。"""
    try:
        return int(getattr(settings, "llm_max_tokens", 2048))
    except (TypeError, ValueError):
        return 2048


def _llm_temperature() -> float:
    """生成温度；键缺失时回退默认 0.6（Kimi 关闭思考模式唯一允许值）。"""
    try:
        return float(getattr(settings, "llm_temperature", _KIMI_DISABLED_THINKING_TEMPERATURE))
    except (TypeError, ValueError):
        return _KIMI_DISABLED_THINKING_TEMPERATURE


def _llm_disable_thinking() -> bool:
    """是否关闭推理模型的思考模式（Kimi 默认关闭）；键缺失时回退 ``True``。"""
    raw = getattr(settings, "llm_disable_thinking", True)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on", ""}
    return bool(raw)


class LLMService:
    """流式对话客户端（懒加载客户端单例）。"""

    def __init__(self) -> None:
        # 惰性构建客户端：未配置 key 时不创建任何网络客户端
        self._client: AsyncOpenAI | None = None

    @property
    def is_configured(self) -> bool:
        """``settings.deepseek_api_key`` 非空即视为已配置。"""
        key = getattr(settings, "deepseek_api_key", "") or ""
        return bool(key.strip())

    def _get_client(self) -> AsyncOpenAI:
        """构建（并缓存）AsyncOpenAI 客户端。"""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                timeout=httpx.Timeout(_llm_timeout_seconds(), connect=10.0),
                max_retries=0,
            )
        return self._client

    def _build_kwargs(
        self,
        messages: list[dict],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict:
        """组装请求参数：关闭思考 + temperature 约束（Kimi 硬约束 1/2）。"""
        disable_thinking = _llm_disable_thinking()
        temp = _llm_temperature() if temperature is None else temperature
        if disable_thinking and abs(temp - _KIMI_DISABLED_THINKING_TEMPERATURE) > 1e-9:
            logger.warning(
                f"关闭思考模式下 temperature 必须为 {_KIMI_DISABLED_THINKING_TEMPERATURE}"
                f"（当前 {temp}），已强制纠正"
            )
            temp = _KIMI_DISABLED_THINKING_TEMPERATURE

        kwargs: dict = {
            "model": settings.llm_model,
            "messages": messages,
            "stream": stream,
            "temperature": temp,
            "max_tokens": _llm_max_tokens() if max_tokens is None else max_tokens,
        }
        if disable_thinking:
            # 关键：关闭推理模型的思考，避免 reasoning_content 吃光 token 导致 content 为空
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        return kwargs

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式产出**增量文本 token**（仅 ``content``，不含 ``reasoning_content``）。

        Args:
            messages: ``[{"role": "system|user|assistant", "content": str}]``。
            temperature: 生成温度，缺省取 ``settings.llm_temperature``（关闭思考时强制 0.6）。
            max_tokens: 生成上限，缺省取 ``settings.llm_max_tokens``。

        Yields:
            增量文本片段（非空字符串）。

        Raises:
            LLMUnavailableError: 未配置 key，或首包前连接失败（含重试后仍失败）。
            LLMRateLimitError: 触发限流（429）——直接降级，不重试。
            LLMStreamError: 流式建立之后中途失败（调用方需保留已产出文本）。
        """
        if not self.is_configured:
            raise LLMUnavailableError("DEEPSEEK_API_KEY 未配置")

        client = self._get_client()
        kwargs = self._build_kwargs(messages, stream=True, temperature=temperature, max_tokens=max_tokens)

        # 首包前（连接/建流）：仅网络错误重试 1 次；429 与其它 HTTP 状态错误**不重试**
        stream = None
        last_exc: Exception | None = None
        rate_limited = False
        for attempt in range(2):
            try:
                stream = await client.chat.completions.create(**kwargs)
                break
            except RateLimitError as exc:
                # 限流：直接放弃重试（重试会加剧 429）
                rate_limited = True
                last_exc = exc
                logger.warning(f"DeepSeek/Kimi 限流 429（不重试）：{exc}")
                break
            except APITimeoutError as exc:  # APITimeoutError 是 APIConnectionError 子类
                last_exc = exc
                logger.warning(f"LLM 连接超时（第 {attempt + 1} 次）：{exc}")
            except APIConnectionError as exc:
                last_exc = exc
                logger.warning(f"LLM 连接失败（第 {attempt + 1} 次）：{exc}")
            except APIStatusError as exc:
                last_exc = exc
                logger.error(f"LLM 返回错误状态 {exc.status_code}，不再重试：{exc}")
                break
        if stream is None:
            if rate_limited:
                raise LLMRateLimitError(f"大模型接口限流 429：{last_exc}")
            raise LLMUnavailableError(f"大模型服务不可用：{last_exc}")

        # 流式迭代：中途失败不重试，抛异常由调用方处理（保留已产出文本）
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield text
        except RateLimitError as exc:
            logger.warning(f"LLM 流式中途被限流 429：{exc}")
            raise LLMRateLimitError(f"流式中途限流 429：{exc}") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            logger.error(f"LLM 流式中途连接失败：{exc}")
            raise LLMStreamError(f"流式中断：{exc}") from exc
        except APIStatusError as exc:
            logger.error(f"LLM 流式中途返回错误状态 {exc.status_code}：{exc}")
            raise LLMStreamError(f"流式中断：{exc}") from exc

    async def complete(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMChatResult:
        """非流式补全（可用于生成会话标题等轻量场景）。

        Raises:
            LLMUnavailableError: 未配置 key 或调用失败。
            LLMRateLimitError: 触发限流（429）。
        """
        if not self.is_configured:
            raise LLMUnavailableError("DEEPSEEK_API_KEY 未配置")

        client = self._get_client()
        kwargs = self._build_kwargs(messages, stream=False, temperature=temperature, max_tokens=max_tokens)
        started = time.monotonic()
        try:
            resp = await client.chat.completions.create(**kwargs)
        except RateLimitError as exc:
            raise LLMRateLimitError(f"大模型接口限流 429：{exc}") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise LLMUnavailableError(f"大模型服务不可用：{exc}") from exc
        except APIStatusError as exc:
            logger.error(f"LLM 返回错误状态 {exc.status_code}：{exc}")
            raise LLMUnavailableError(f"大模型服务不可用：{exc}") from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)
        choice = resp.choices[0] if resp.choices else None
        text = ""
        finish_reason: str | None = None
        if choice is not None:
            finish_reason = choice.finish_reason
            message = getattr(choice, "message", None)
            if message is not None:
                text = message.content or ""
        return LLMChatResult(text=text, finish_reason=finish_reason, elapsed_ms=elapsed_ms)


# 模块级单例：全项目统一从此处引用
llm_service = LLMService()


__all__ = [
    "LLMError",
    "LLMUnavailableError",
    "LLMRateLimitError",
    "LLMStreamError",
    "LLMChatResult",
    "LLMService",
    "llm_service",
]
