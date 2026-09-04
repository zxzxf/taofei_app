"""OpenAI 兼容端点直连 provider。

目标：去掉 agent 对话路径对 taofei_api.LLM（litellm/多 provider 封装）的依赖，
直接用 openai SDK 调 /v1/chat/completions。收益：
- 单次调用省去中间层开销（50-150ms）
- 拿到原生 usage（含 DeepSeek 前缀缓存字段 prompt_cache_hit_tokens）
- HTTP client 连接池复用（按 base_url+api_key 缓存，避免每次新建）
"""
from __future__ import annotations

import threading
import time
from typing import Any

try:
    import openai
    HAS_OPENAI = True
except ImportError:  # pragma: no cover
    openai = None
    HAS_OPENAI = False

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


class OpenAICompatLLM:
    """OpenAI 兼容端点直连 LLM。

    接口面与 taofei_api.LLM 在 main.py / runner 中使用的部分保持一致：
    - ``.model``：模型名
    - ``.call(messages, tools=None)``：同步调用
      - 无 tools（或空）→ 返回 **str**（choices[0].message.content）
      - 有 tools → 返回 openai **ChatCompletion** 对象（.message / .usage / .choices）
    - ``._get_sync_client()``：返回共享 openai client（供流式直连复用）
    - ``.last_usage``：最近一次调用的 usage dict
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        if not HAS_OPENAI:
            raise RuntimeError("openai SDK 未安装")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.last_usage: dict | None = None

    # ---------------------------------------------------------
    # 内部
    # ---------------------------------------------------------
    def _client(self) -> Any:
        return _get_client(self.api_key, self.base_url, self.timeout)

    def _get_sync_client(self) -> Any:
        """兼容 main.py llm_stream_fn 的直连用法。"""
        return self._client()

    # ---------------------------------------------------------
    # 同步调用
    # ---------------------------------------------------------
    def call(self, messages: Any, tools: list[dict] | None = None, **kwargs: Any) -> Any:
        """同步 chat.completions 调用。

        messages 兼容 str（自动包装为单条 user 消息）。
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        params: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = tools
        if kwargs:
            # 过滤 None 值，避免 SDK 报错
            params.update({k: v for k, v in kwargs.items() if v is not None})

        resp = self._client().chat.completions.create(**params)
        self.last_usage = usage_to_dict(getattr(resp, "usage", None))

        if not tools:
            # 与 taofei_api.LLM.call 语义一致：无 tools 返回文本
            try:
                return resp.choices[0].message.content or ""
            except Exception:
                return ""
        return resp

    # ---------------------------------------------------------
    # 流式调用（原生流，由 main.py 的 llm_stream_fn 消费）
    # ---------------------------------------------------------
    def stream_chat(self, messages: Any, tools: list[dict] | None = None, **kwargs: Any):
        """流式 chat.completions 调用，返回 SDK stream 迭代器。

        kwargs 需含 stream=True 时由调用方保证；本方法自动补上。
        """
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
        return f"<OpenAICompatLLM model={self.model} base_url={self.base_url or 'default'}>"
