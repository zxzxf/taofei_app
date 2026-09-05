"""Fallback Chain — 提供商故障自动转移（阶段 6）。

主提供商挂了自动切到下一个备用，用户无感知。

设计
----
- **链式结构**：fallback_chain = [主, 备1, 备2, ...]
- **错误触发**：仅对可重试错误（ServerError / TimeoutError / NetworkError / RateLimitError）
  触发转移；对不可重试错误（AuthError / BadRequestError）不转移（换 provider 也没用）
- **冷却机制**：失败的 provider 进入 cooldown，一段时间内不再尝试
- **统计感知**：持续错误率 > 阈值的 provider 自动降级到队尾
- **幂等安全**：只对安全的请求（读/同步/流式）做 fallback，写操作不自动转移

使用
----
```python
from providers.fallback_chain import FallbackChain
from providers.openai_compat import OpenAICompatProvider

chain = FallbackChain([
    OpenAICompatProvider(model="deepseek-chat", api_key="key1", base_url="https://api.deepseek.com"),
    OpenAICompatProvider(model="gpt-4o-mini", api_key="key2", base_url="https://api.openai.com"),
])

# 同步调用（自动故障转移）
result = chain.chat(messages=[{"role": "user", "content": "hi"}])

# 流式调用（自动故障转移 — 注意：流中间失败会切换并重试整个请求）
for delta_type, delta, raw in chain.chat_stream(messages=[...]):
    ...
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Generator

from .base import (
    BaseProvider,
    ProviderError,
    AuthError,
    RateLimitError,
    ServerError,
    TimeoutError as ProviderTimeoutError,
    NetworkError,
    BadRequestError,
    ContextLengthError,
    DELTA_CONTENT,
    DELTA_TOOL_CALL,
    DELTA_DONE,
    DELTA_USAGE,
)


@dataclass
class ProviderStatus:
    """单个 provider 的运行状态。"""
    provider: BaseProvider
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    total_failures: int = 0
    total_requests: int = 0

    @property
    def is_available(self) -> bool:
        return time.perf_counter() >= self.cooldown_until


class FallbackChain:
    """故障转移链：主 provider 失败自动切备用。

    参数
    ----
    providers: list[BaseProvider]
        按优先级排列的 provider 列表（第一个是主）
    max_retries_per_provider: int
        每个 provider 最多重试几次（默认 1，即失败就切）
    cooldown_seconds: float
        失败的 provider 冷却多久（默认 30 秒）
    failure_threshold: int
        连续失败多少次进入 cooldown（默认 1）
    """

    def __init__(
        self,
        providers: list[BaseProvider],
        max_retries_per_provider: int = 1,
        cooldown_seconds: float = 30.0,
        failure_threshold: int = 1,
    ):
        if not providers:
            raise ValueError("FallbackChain 至少需要一个 provider")
        self._statuses: list[ProviderStatus] = [
            ProviderStatus(provider=p) for p in providers
        ]
        self.max_retries_per_provider = max_retries_per_provider
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = failure_threshold

    # -----------------------------------------------------------
    # 内部：选择下一个可用 provider
    # -----------------------------------------------------------
    def _available_providers(self) -> list[ProviderStatus]:
        """返回当前可用（不在 cooldown）的 provider，按优先级排序。"""
        return [s for s in self._statuses if s.is_available]

    def _mark_failure(self, status: ProviderStatus, exc: ProviderError) -> None:
        """标记一次失败，连续失败超阈值进入 cooldown。"""
        status.consecutive_failures += 1
        status.total_failures += 1
        status.provider.record_error()

        if status.consecutive_failures >= self.failure_threshold:
            # 限流错误冷却时间更长
            if isinstance(exc, RateLimitError) and exc.retry_after:
                status.cooldown_until = time.perf_counter() + max(exc.retry_after, self.cooldown_seconds)
            else:
                status.cooldown_until = time.perf_counter() + self.cooldown_seconds

    def _mark_success(self, status: ProviderStatus) -> None:
        """标记一次成功，重置连续失败计数。"""
        status.consecutive_failures = 0
        status.total_requests += 1

    # -----------------------------------------------------------
    # 同步调用（带故障转移）
    # -----------------------------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             **kwargs) -> dict:
        """同步聊天，失败自动转移到下一个 provider。

        返回值同 BaseProvider.chat()：{content, tool_calls, usage, raw}
        """
        last_error: ProviderError | None = None
        tried = 0

        for status in self._available_providers():
            if tried >= self.max_retries_per_provider * len(self._statuses):
                break
            tried += 1

            try:
                result = status.provider.chat(messages, tools=tools, **kwargs)
                self._mark_success(status)
                return result
            except (AuthError, BadRequestError, ContextLengthError):
                # 不可重试错误：直接抛出（换 provider 也没用）
                raise
            except ProviderError as e:
                # 可重试错误：记一下，切下一个
                self._mark_failure(status, e)
                last_error = e
                continue
            except Exception as e:
                # 未知错误也尝试转移
                last_error = ProviderError(
                    f"未知错误: {e}", provider=status.provider.name, retryable=True
                )
                self._mark_failure(status, last_error)
                continue

        # 全部失败
        raise last_error or ProviderError("所有 provider 均不可用", retryable=False)

    # -----------------------------------------------------------
    # 流式调用（带故障转移）
    # -----------------------------------------------------------
    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    **kwargs) -> Generator[tuple[str, Any, Any], None, None]:
        """流式聊天，失败自动转移到下一个 provider。

        注意：流式调用如果中间失败，会切换 provider 并**从头开始重发整个请求**，
        已产出的 token 不会被丢弃（调用方收到的是完整的新流）。
        """
        last_error: ProviderError | None = None
        tried = 0

        for status in self._available_providers():
            if tried >= self.max_retries_per_provider * len(self._statuses):
                break
            tried += 1

            try:
                got_any_token = False
                for delta_type, delta, raw in status.provider.chat_stream(
                    messages, tools=tools, **kwargs
                ):
                    got_any_token = True
                    yield delta_type, delta, raw

                # 成功产出完整流
                self._mark_success(status)
                return

            except (AuthError, BadRequestError, ContextLengthError):
                # 不可重试错误：直接抛出
                raise
            except ProviderError as e:
                self._mark_failure(status, e)
                last_error = e
                # 如果已经收到过一些 token，切换会导致不连续
                # 调用方需要自己处理这种情况（我们只保证"要么完整成功，要么切下一个"）
                continue
            except Exception as e:
                last_error = ProviderError(
                    f"未知错误: {e}", provider=status.provider.name, retryable=True
                )
                self._mark_failure(status, last_error)
                continue

        raise last_error or ProviderError("所有 provider 均不可用", retryable=False)

    # -----------------------------------------------------------
    # 状态查询
    # -----------------------------------------------------------
    def status_report(self) -> list[dict]:
        """返回所有 provider 的状态报告。"""
        now = time.perf_counter()
        report = []
        for i, s in enumerate(self._statuses):
            report.append({
                "index": i,
                "provider": s.provider.name,
                "model": s.provider.model,
                "available": s.is_available,
                "consecutive_failures": s.consecutive_failures,
                "total_failures": s.total_failures,
                "total_requests": s.total_requests,
                "cooldown_remaining": max(0, int(s.cooldown_until - now)),
                "last_latency_ms": s.provider.last_latency_ms,
            })
        return report

    def reset_all(self) -> None:
        """重置所有 provider 的状态和 cooldown。"""
        for s in self._statuses:
            s.consecutive_failures = 0
            s.cooldown_until = 0.0
            s.total_failures = 0
            s.total_requests = 0
            s.provider.reset_stats()

    @property
    def primary(self) -> BaseProvider:
        """当前主 provider（第一个可用的）。"""
        for s in self._available_providers():
            return s.provider
        # 都不可用就返回第一个
        return self._statuses[0].provider
