"""OpenAI 兼容端点直连 provider（阶段 6 改造：继承 BaseProvider）。

目标：去掉 agent 对话路径对 taofei_api.LLM（litellm/多 provider 封装）的依赖，
直接用 openai SDK 调 /v1/chat/completions。收益：
- 单次调用省去中间层开销（50-150ms）
- 拿到原生 usage（含 DeepSeek 前缀缓存字段 prompt_cache_hit_tokens）
- HTTP client 连接池复用（按 base_url+api_key 缓存，避免每次新建）

向后兼容
--------
旧代码使用 ``.call(messages, tools=None)`` 和 ``._get_sync_client()`` 的方式
继续可用，不破坏现有调用链。新代码请使用基类标准接口 ``.chat()`` / ``.chat_stream()``。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Generator

try:
    import openai
    HAS_OPENAI = True
except ImportError:  # pragma: no cover
    openai = None
    HAS_OPENAI = False

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


# 连接池：{(base_url, api_key): openai.OpenAI}
_client_cache: dict[tuple[str, str], Any] = {}
_client_lock = threading.Lock()
_client_created_at: dict[tuple[str, str], float] = {}


def _get_client(api_key: str | None, base_url: str | None, timeout: float = 120.0) -> Any:
    """获取共享 openai client（连接池复用）。"""
    key = ((base_url or "").rstrip("/"), api_key or "")
    with _client_lock:
        client = _client_cache.get(key)
        if client is None:
            kwargs: dict[str, Any] = {
                "api_key": api_key or "EMPTY",
                "timeout": timeout,
                "max_retries": 2,
            }
            if base_url:
                kwargs["base_url"] = base_url
            client = openai.OpenAI(**kwargs)
            _client_cache[key] = client
            _client_created_at[key] = time.time()
        return client


def usage_to_dict(usage: Any) -> dict | None:
    """把 CompletionUsage 转成 dict（保留未知字段，如 DeepSeek 缓存计数）。"""
    if usage is None:
        return None
    try:
        if hasattr(usage, "model_dump"):
            data = usage.model_dump()
        elif hasattr(usage, "dict"):
            data = usage.dict()
        else:
            data = dict(usage)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def format_usage(usage: dict | None) -> str:
    """usage dict → 可读统计文本（含 DeepSeek 前缀缓存）。"""
    if not usage:
        return ""
    parts = []
    p = usage.get("prompt_tokens")
    c = usage.get("completion_tokens")
    t = usage.get("total_tokens")
    if p is not None:
        hit = usage.get("prompt_cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens")
        cache_part = ""
        if hit is not None or miss is not None:
            cache_part = f" (缓存命中 {hit or 0} / 未命中 {miss or 0})"
        parts.append(f"prompt={p}{cache_part}")
    if c is not None:
        parts.append(f"completion={c}")
    if t is not None:
        parts.append(f"total={t}")
    return ", ".join(parts)


def _classify_openai_error(exc: Exception) -> ProviderError:
    """把 openai SDK 异常映射为我们的 ProviderError 子类。"""
    msg = str(exc)
    exc_type = type(exc).__name__

    # openai SDK 异常类名映射
    if "AuthenticationError" in exc_type or "Unauthorized" in exc_type or "401" in msg:
        return AuthError(msg, provider="openai_compat")
    if "RateLimitError" in exc_type or "429" in msg or "rate_limit" in msg:
        return RateLimitError(msg, provider="openai_compat")
    if "BadRequestError" in exc_type or "400" in msg:
        if "context_length_exceeded" in msg or "maximum context length" in msg:
            return ContextLengthError(msg, provider="openai_compat")
        return BadRequestError(msg, provider="openai_compat")
    if "InternalServerError" in exc_type or "500" in msg or "503" in msg or "502" in msg:
        return ServerError(msg, provider="openai_compat")
    if "Timeout" in exc_type or "timeout" in msg.lower():
        return ProviderTimeoutError(msg, provider="openai_compat")
    if "APIConnectionError" in exc_type or "Connection" in exc_type or "DNS" in msg or "connect" in msg.lower():
        return NetworkError(msg, provider="openai_compat")

    # 默认：服务端错误（可重试）
    return ServerError(msg, provider="openai_compat")


class OpenAICompatProvider(BaseProvider):
    """OpenAI 兼容端点 provider（标准基类接口）。

    支持所有 OpenAI 兼容 API：OpenAI / DeepSeek / 智谱 / Moonshot / 通义 /
    本地 Ollama / vLLM / LM Studio 等。
    """

    name = "openai_compat"

    def _client(self) -> Any:
        return _get_client(self.api_key, self.base_url, self.timeout)

    def _get_sync_client(self) -> Any:
        """兼容旧接口：返回原生 openai client。"""
        return self._client()

    # -----------------------------------------------------------
    # 同步调用（标准接口）
    # -----------------------------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             **kwargs) -> dict:
        """同步聊天补全，返回统一格式 dict。"""
        start = time.perf_counter()
        try:
            params: dict[str, Any] = {"model": self.model, "messages": messages}
            if tools:
                params["tools"] = tools
            params.update({k: v for k, v in kwargs.items() if v is not None})

            resp = self._client().chat.completions.create(**params)
            usage = usage_to_dict(getattr(resp, "usage", None))
            self.record_usage(usage, start)

            content = ""
            tool_calls: list[dict] = []
            try:
                msg = resp.choices[0].message
                content = msg.content or ""
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        args_dict = {}
                        try:
                            import json
                            args_dict = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            args_dict = {"raw": tc.function.arguments or ""}
                        tool_calls.append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": args_dict,
                        })
            except Exception:
                pass

            return {
                "content": content,
                "tool_calls": tool_calls,
                "usage": usage,
                "raw": resp,
            }
        except Exception as e:
            self.record_error()
            raise _classify_openai_error(e)

    # -----------------------------------------------------------
    # 流式调用（标准接口）
    # -----------------------------------------------------------
    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    **kwargs) -> Generator[tuple[str, Any, Any], None, None]:
        """流式聊天补全，生成器 yield (delta_type, delta_value, raw_chunk)。"""
        start = time.perf_counter()
        try:
            params: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools:
                params["tools"] = tools
            params.update({k: v for k, v in kwargs.items() if v is not None})

            stream = self._client().chat.completions.create(**params)

            content_parts: list[str] = []
            tool_call_states: dict[int, dict] = {}
            final_usage = None
            full_response = None

            for chunk in stream:
                if not chunk.choices:
                    # 可能是 usage chunk
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        final_usage = usage_to_dict(chunk.usage)
                        yield DELTA_USAGE, final_usage, chunk
                    continue

                delta = chunk.choices[0].delta

                # 文本 token
                if delta.content is not None:
                    content_parts.append(delta.content)
                    yield DELTA_CONTENT, delta.content, chunk

                # 工具调用增量
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_states:
                            tool_call_states[idx] = {
                                "id": "", "name": "", "args_parts": []
                            }
                        if tc_delta.id:
                            tool_call_states[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            tool_call_states[idx]["name"] += tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            tool_call_states[idx]["args_parts"].append(
                                tc_delta.function.arguments
                            )
                        tc_dict = {
                            "index": idx,
                            "id": tool_call_states[idx]["id"],
                            "name": tool_call_states[idx]["name"],
                            "arguments": "".join(tool_call_states[idx]["args_parts"]),
                        }
                        yield DELTA_TOOL_CALL, tc_dict, chunk

            # done 事件：构造完整响应
            full_tool_calls: list[dict] = []
            import json as _j
            for idx in sorted(tool_call_states.keys()):
                st = tool_call_states[idx]
                try:
                    args_dict = _j.loads("".join(st["args_parts"]) or "{}")
                except Exception:
                    args_dict = {"raw": "".join(st["args_parts"])}
                full_tool_calls.append({
                    "id": st["id"],
                    "name": st["name"],
                    "arguments": args_dict,
                })

            full_response = {
                "content": "".join(content_parts),
                "tool_calls": full_tool_calls,
                "usage": final_usage,
            }
            self.record_usage(final_usage, start)
            yield DELTA_DONE, full_response, stream

        except Exception as e:
            self.record_error()
            raise _classify_openai_error(e)

    # -----------------------------------------------------------
    # 兼容旧接口（保留 .call() 方法，不破坏现有代码）
    # -----------------------------------------------------------
    def call(self, messages: Any, tools: list[dict] | None = None, **kwargs: Any) -> Any:
        """旧接口兼容：与 taofei_api.LLM.call 语义一致。

        - 无 tools → 返回 str（文本内容）
        - 有 tools → 返回原生 ChatCompletion 对象
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        params: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = tools
        params.update({k: v for k, v in kwargs.items() if v is not None})

        start = time.perf_counter()
        try:
            resp = self._client().chat.completions.create(**params)
            self.last_usage = usage_to_dict(getattr(resp, "usage", None))
            self.last_latency_ms = int((time.perf_counter() - start) * 1000)

            if not tools:
                try:
                    return resp.choices[0].message.content or ""
                except Exception:
                    return ""
            return resp
        except Exception as e:
            self.record_error()
            # 旧接口不抛 ProviderError（怕破坏现有 try/except），保留原异常
            raise e

    def stream_chat(self, messages: Any, tools: list[dict] | None = None, **kwargs: Any):
        """旧接口兼容：返回原生 SDK stream 迭代器。"""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = tools
        params.update({k: v for k, v in kwargs.items() if v is not None})
        return self._client().chat.completions.create(**params)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OpenAICompatProvider model={self.model} base_url={self.base_url or 'default'}>"


# 向后兼容别名：旧代码 from providers.openai_compat import OpenAICompatLLM 继续可用
OpenAICompatLLM = OpenAICompatProvider
