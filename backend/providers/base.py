"""Provider 基类（阶段 6：多提供商 + 故障转移）。

所有 LLM 提供商实现此接口，上层（Agent / Chat）只依赖基类，
不感知具体提供商，实现可插拔切换 + 故障转移。

设计原则
--------
- **统一数据结构**：消息格式统一使用 OpenAI 风格 dict
  (``{"role": "system"/"user"/"assistant"/"tool", "content": ...}``)
- **流式统一**：``chat_stream()`` 返回生成器，yield 三元组
  ``(delta_type: str, delta_value: Any, raw_chunk: Any)``
- **usage 统一**：每次调用后 ``last_usage`` 包含标准字段 + 提供商专属字段
- **错误分类**：所有提供商抛出的异常统一为 ``ProviderError`` 子类，
  上层据此决定是否重试 / 降级 / 切换提供商
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator


# ------------------------------------------------------------------
# 错误类型
# ------------------------------------------------------------------
class ProviderError(Exception):
    """所有 provider 错误的基类。"""

    def __init__(self, message: str, provider: str = "", model: str = "",
                 retryable: bool = False, **kwargs):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.retryable = retryable
        self.extra = kwargs


class AuthError(ProviderError):
    """API Key 无效 / 配额耗尽 / 未授权。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, retryable=False, **kw)


class RateLimitError(ProviderError):
    """限流 / 速率超限。可重试（等一会）。"""
    def __init__(self, *a, retry_after: float | None = None, **kw):
        super().__init__(*a, retryable=True, **kw)
        self.retry_after = retry_after


class ServerError(ProviderError):
    """服务端 5xx / 过载。可重试。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, retryable=True, **kw)


class TimeoutError(ProviderError):
    """请求超时。可重试。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, retryable=True, **kw)


class NetworkError(ProviderError):
    """网络连接错误（DNS / 连接失败 / TLS）。可重试。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, retryable=True, **kw)


class BadRequestError(ProviderError):
    """400 / 参数错误。不可重试（重试也没用）。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, retryable=False, **kw)


class ContextLengthError(BadRequestError):
    """上下文超长。不可重试（需要压缩上下文）。"""
    pass


# ------------------------------------------------------------------
# 流式 delta 类型常量
# ------------------------------------------------------------------
DELTA_CONTENT = "content"
DELTA_TOOL_CALL = "tool_call_delta"
DELTA_DONE = "done"
DELTA_USAGE = "usage"


# ------------------------------------------------------------------
# Provider 基类
# ------------------------------------------------------------------
class BaseProvider(ABC):
    """LLM 提供商抽象基类。

    子类必须实现：``chat()`` / ``chat_stream()`` / ``embed()``

    标准属性：
    - ``name``: 提供商名称（如 "openai" / "deepseek" / "anthropic"）
    - ``model``: 当前模型名
    - ``last_usage``: 最近一次调用的 usage dict
    - ``last_latency_ms``: 最近一次调用耗时（毫秒）
    """

    name: str = "base"

    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, timeout: float = 120.0):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.last_usage: dict | None = None
        self.last_latency_ms: int = 0
        self._request_count = 0
        self._error_count = 0

    # -----------------------------------------------------------
    # 抽象接口
    # -----------------------------------------------------------
    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             **kwargs) -> dict:
        """同步聊天补全。

        返回 dict：
        {
            "content": str,                    # 文本内容（可能为空字符串）
            "tool_calls": [                    # 工具调用（可能为空列表）
                {"id": str, "name": str, "arguments": dict}
            ],
            "usage": {...},                    # usage 信息
            "raw": Any,                        # 原始响应（调试用）
        }
        """
        ...

    @abstractmethod
    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    **kwargs) -> Generator[tuple[str, Any, Any], None, None]:
        """流式聊天补全。

        生成器 yield 三元组 ``(delta_type, delta_value, raw_chunk)``:
        - ``("content", str, chunk)`` — 文本 token
        - ``("tool_call_delta", {index, id, name, arguments}, chunk)`` — 工具调用增量
        - ``("usage", {...}, chunk)`` — usage 信息（流式最后一条）
        - ``("done", full_response, chunk)`` — 完成，返回完整响应

        生成器结束时也会 yield 一个 done 事件。
        """
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量嵌入。可选实现，不支持则抛 NotImplementedError。"""
        raise NotImplementedError(f"Provider {self.name} 不支持 embedding")

    # -----------------------------------------------------------
    # 公共工具方法
    # -----------------------------------------------------------
    def record_usage(self, usage: dict | None, start_time: float) -> None:
        """记录本次调用的 usage 和耗时。"""
        self.last_usage = usage
        self.last_latency_ms = int((time.perf_counter() - start_time) * 1000)
        self._request_count += 1

    def record_error(self) -> None:
        """记录一次错误。"""
        self._error_count += 1

    @property
    def error_rate(self) -> float:
        """近期错误率（0-1）。"""
        if self._request_count == 0:
            return 0.0
        return self._error_count / self._request_count

    def reset_stats(self) -> None:
        """重置统计。"""
        self._request_count = 0
        self._error_count = 0

    # -----------------------------------------------------------
    # 健康检查
    # -----------------------------------------------------------
    def health_check(self) -> dict:
        """简单健康检查：发一个短消息看是否能正常响应。

        返回 ``{"ok": bool, "latency_ms": int, "error": str}``
        """
        start = time.perf_counter()
        try:
            result = self.chat(
                [{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return {
                "ok": True,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": "",
            }
        except ProviderError as e:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": str(e),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": f"未知错误: {e}",
            }

    # -----------------------------------------------------------
    # 描述
    # -----------------------------------------------------------
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.model}>"
