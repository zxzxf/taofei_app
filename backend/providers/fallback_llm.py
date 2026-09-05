# -*- coding: utf-8 -*-
"""FallbackLLM —— 旧接口兼容的故障转移门面（阶段 6.7）。

背景
----
阶段 6 核心架构（base / openai_compat / anthropic / fallback_chain / registry）
在 5087b4c 已就绪，但 main.py 全链路仍在使用 ``taofei_api.LLM`` 时代的
**旧接口**：``.call(messages)`` → str、``.call(messages, tools=)`` → 原生
ChatCompletion、``._get_sync_client()`` 裸 client 流式。这些调用点无法直接
换成 ``FallbackChain``（它只提供新标准接口 ``chat()`` / ``chat_stream()``）。

本模块提供 **FallbackLLM 门面**：外形与 ``OpenAICompatLLM`` 完全一致，
内部持有 ``FallbackChain``，把旧接口调用翻译到标准接口，从而：
- 4 个调用点（/api/chat、workflow、agent FC、agent streaming）**零改动**
- 同步调用 ``.call()`` 自动故障转移
- 流式 ``.chat_stream()`` 自动故障转移（中间失败切备用重发整请求）
- ``.model`` / ``.last_usage`` / ``.last_latency_ms`` 等属性透传主 provider

设计
----
- 主 provider = 用户当前配置（model_config.json / preset）
- 备用 provider = registry 中其它已启用、且与主 provider 不同 base_url 的配置
- 只有一个可用 provider 时，``_build_llm`` 直接返回原对象（零开销、零行为变化）
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

from .fallback_chain import FallbackChain
from .base import (
    DELTA_CONTENT,
    DELTA_TOOL_CALL,
    DELTA_DONE,
    DELTA_USAGE,
    ProviderError,
)


class FallbackLLM:
    """外形兼容 OpenAICompatLLM 的故障转移门面。

    用法（与 OpenAICompatLLM 相同）::

        llm = FallbackLLM(chain_or_providers)
        text = llm.call(messages)                    # str
        resp = llm.call(messages, tools=openai_tools)  # SimpleNamespace(message=...)
        for dt, dv in llm.chat_stream(messages, tools=openai_tools): ...  # 标准流
    """

    def __init__(self, chain_or_providers: FallbackChain | list[Any]):
        if isinstance(chain_or_providers, FallbackChain):
            self._chain: FallbackChain = chain_or_providers
        else:
            if not chain_or_providers:
                raise ValueError("FallbackLLM 至少需要一个 provider")
            self._chain = FallbackChain(chain_or_providers)

        # 镜像主 provider 的属性，让旧代码 getattr 全部可用
        self._primary = self._chain.primary
        self.name = getattr(self._primary, "name", "fallback")
        self.model = getattr(self._primary, "model", "")
        self.base_url = getattr(self._primary, "base_url", "")
        self.api_key = getattr(self._primary, "api_key", "")
        self.timeout = getattr(self._primary, "timeout", 120.0)
        # usage / 延迟由最后一次成功调用更新
        self.last_usage: dict | None = None
        self.last_latency_ms: int = 0
        self._last_result: dict | None = None

    # ---------------------------------------------------------------
    # 状态查询
    # ---------------------------------------------------------------
    @property
    def chain(self) -> FallbackChain:
        return self._chain

    def status_report(self) -> list[dict]:
        """各 provider 的健康状态（供 /api/providers/status 使用）。"""
        return self._chain.status_report()

    def last_error(self) -> str | None:
        """最近一次全链失败的 ProviderError 信息（无则 None）。"""
        return getattr(self, "_last_error", None)

    # ---------------------------------------------------------------
    # 旧接口：.call()（/api/chat、workflow、agent FC 共用）
    # ---------------------------------------------------------------
    def call(self, messages: Any, tools: list[dict] | None = None, **kwargs: Any) -> Any:
        """与 taofei_api.LLM.call / OpenAICompatLLM.call 语义一致。

        - 无 tools → 返回 str（纯文本）
        - 有 tools → 返回 SimpleNamespace(message=...)，message.content /
          message.tool_calls 与 openai SDK ChatCompletion 兼容
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        try:
            result = self._chain.chat(messages, tools=tools, **kwargs)
        except ProviderError as e:
            self._last_error = str(e)
            raise
        self._last_error = None
        self._last_result = result
        self.last_usage = result.get("usage")
        # 取成功 provider 的耗时（fallback 可能切到备用）
        self.last_latency_ms = self._last_latency_from_chain()

        if not tools:
            return result.get("content") or ""

        # 有 tools：构造成 openai SDK 兼容对象（FC runner 直接消费）
        content = result.get("content") or ""
        tool_calls = []
        for tc in result.get("tool_calls") or []:
            args = tc.get("arguments")
            if isinstance(args, dict):
                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = str(args or "")
            tool_calls.append(SimpleNamespace(
                id=tc.get("id") or "",
                type="function",
                function=SimpleNamespace(
                    name=tc.get("name") or "",
                    arguments=args_str,
                ),
            ))
        return SimpleNamespace(message=SimpleNamespace(
            content=content,
            tool_calls=tool_calls,
        ))

    def _last_latency_from_chain(self) -> int:
        """从 chain 中取最近一次成功调用的耗时。"""
        best = 0
        for s in getattr(self._chain, "_statuses", []):
            p = s.provider
            if p.last_latency_ms:
                best = max(best, int(p.last_latency_ms))
        return best

    # ---------------------------------------------------------------
    # 标准接口：chat() / chat_stream()（新代码可直接用）
    # ---------------------------------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             **kwargs: Any) -> dict:
        """标准同步接口，返回 {content, tool_calls, usage, raw}。"""
        result = self._chain.chat(messages, tools=tools, **kwargs)
        self.last_usage = result.get("usage")
        self.last_latency_ms = self._last_latency_from_chain()
        return result

    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    **kwargs: Any):
        """标准流式接口：yield (delta_type, delta, raw_chunk)。

        delta_type ∈ content / tool_call_delta / usage / done
        自动故障转移：主 provider 中途失败会切备用并重发整个请求。
        """
        last_error = None
        try:
            for dt, dv, raw in self._chain.chat_stream(messages, tools=tools, **kwargs):
                if dt == DELTA_DONE:
                    self.last_usage = dv.get("usage") if isinstance(dv, dict) else None
                    self.last_latency_ms = self._last_latency_from_chain()
                yield dt, dv, raw
        except ProviderError as e:
            self._last_error = str(e)
            raise
        except Exception as e:
            self._last_error = str(e)
            raise

    # ---------------------------------------------------------------
    # 旧流式接口：stream_chat / _get_sync_client（尽量兼容）
    # ---------------------------------------------------------------
    def stream_chat(self, messages: Any, tools: list[dict] | None = None, **kwargs: Any):
        """旧接口兼容：返回 (delta_type, delta, raw) 迭代器。

        注意与 OpenAICompatLLM.stream_chat（返回原生 SDK stream 迭代器）不同：
        这里返回标准三元组流。调用方按标准事件消费即可获得故障转移。
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        return self.chat_stream(messages, tools=tools, **kwargs)

    def _get_sync_client(self) -> Any:
        """兼容占位：FallbackLLM 没有单一底层 client。

        若调用方依赖裸 client 直连（旧 main.py llm_stream_fn），
        会得到带明确提示的异常 —— 应改用 ``chat_stream()`` 标准接口
        才能享受故障转移。
        """
        raise NotImplementedError(
            "FallbackLLM 不提供 _get_sync_client()（故障转移需要走标准接口 "
            "chat_stream()）。请把流式调用迁移到 llm.chat_stream()。"
        )

    # ---------------------------------------------------------------
    # 其它属性透传（旧代码可能读取）
    # ---------------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        # 注意：仅在正常属性查找失败时调用（避免 __init__ 期间递归）
        primary = object.__getattribute__(self, "_primary")
        if hasattr(primary, name):
            return getattr(primary, name)
        raise AttributeError(f"{type(self).__name__} 和主 provider 都没有属性 {name!r}")

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<FallbackLLM primary={self.name}/{self.model} "
                f"backups={len(self._chain._statuses) - 1}>")
