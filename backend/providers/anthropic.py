"""Anthropic 适配器（阶段 6：多提供商）。

将 OpenAI 风格的 messages / tools 转成 Anthropic Messages API 格式，
再把 Anthropic 的响应转回来，对上层透明。

支持的 Anthropic 特有能力：
- 长上下文（200K tokens）
- 工具调用（tool_use / tool_result）
- 流式输出
- prompt caching（系统提示缓存）

注意
----
Anthropic 没有 system role，系统提示通过 ``system`` 参数传递。
工具调用格式也不同（``tool_use`` block / ``tool_result`` block）。
"""
from __future__ import annotations

import time
from typing import Any, Generator

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    anthropic = None
    HAS_ANTHROPIC = False

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


def _classify_anthropic_error(exc: Exception) -> ProviderError:
    """把 anthropic SDK 异常映射为 ProviderError 子类。"""
    msg = str(exc)
    exc_type = type(exc).__name__

    if "AuthenticationError" in exc_type or "401" in msg or "403" in msg:
        return AuthError(msg, provider="anthropic")
    if "RateLimitError" in exc_type or "429" in msg or "rate_limit" in msg:
        return RateLimitError(msg, provider="anthropic")
    if "BadRequestError" in exc_type or "400" in msg:
        if "context_length_exceeded" in msg or "too long" in msg or "overload" in msg:
            return ContextLengthError(msg, provider="anthropic")
        return BadRequestError(msg, provider="anthropic")
    if "InternalServerError" in exc_type or "500" in msg or "503" in msg or "529" in msg:
        return ServerError(msg, provider="anthropic")
    if "Timeout" in exc_type or "timeout" in msg.lower():
        return ProviderTimeoutError(msg, provider="anthropic")
    if "APIConnectionError" in exc_type or "Connection" in exc_type:
        return NetworkError(msg, provider="anthropic")

    return ServerError(msg, provider="anthropic")


def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """把 OpenAI tools 格式转成 Anthropic tools 格式。

    OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
    Anthropic: {"name": ..., "description": ..., "input_schema": {...}}
    """
    result = []
    for t in tools:
        fn = t.get("function", t)
        result.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _openai_messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """把 OpenAI messages 转成 Anthropic 的 (system, messages)。

    - system role 的消息合并成 system 参数
    - user / assistant / tool role 映射
    - tool_calls 转成 tool_use content block
    - tool 角色转成 tool_result content block
    """
    system_parts: list[str] = []
    anthropic_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        system_parts.append(block.get("text", ""))
            continue

        if role == "user":
            if isinstance(content, str):
                anthropic_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                anthropic_messages.append({"role": "user", "content": content})
            continue

        if role == "assistant":
            # 可能有 tool_calls
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # 纯文本
                if isinstance(content, str):
                    anthropic_messages.append({"role": "assistant", "content": content})
                elif isinstance(content, list):
                    anthropic_messages.append({"role": "assistant", "content": content})
                continue

            # 有 tool_calls：转成 text + tool_use blocks
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            import json as _j
            for tc in tool_calls:
                fn = tc.get("function", tc)
                try:
                    inp = _j.loads(fn.get("arguments", "{}") or "{}")
                except Exception:
                    inp = {"raw": fn.get("arguments", "")}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": inp,
                })
            anthropic_messages.append({"role": "assistant", "content": blocks})
            continue

        if role == "tool":
            # Anthropic 的 tool 结果在 user 消息里，类型是 tool_result
            tool_call_id = msg.get("tool_call_id", "")
            anthropic_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content if isinstance(content, str) else str(content),
                }],
            })
            continue

        # 未知角色，跳过
        continue

    system = "\n\n".join(system_parts)
    return system, anthropic_messages


def _anthropic_content_to_openai(content_blocks: list[dict]) -> tuple[str, list[dict]]:
    """把 Anthropic 的 content blocks 转成 OpenAI 格式 (text, tool_calls)。"""
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    import json as _j

    for block in content_blocks:
        btype = block.get("type", "")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "arguments": block.get("input", {}),
            })

    return "".join(text_parts), tool_calls


def _anthropic_usage_to_dict(usage: Any) -> dict | None:
    """把 Anthropic usage 转成标准 dict。"""
    if usage is None:
        return None
    try:
        if hasattr(usage, "model_dump"):
            data = usage.model_dump()
        elif hasattr(usage, "dict"):
            data = usage.dict()
        else:
            data = dict(usage)
        # 字段名映射
        result = {
            "prompt_tokens": data.get("input_tokens", 0),
            "completion_tokens": data.get("output_tokens", 0),
            "total_tokens": (data.get("input_tokens", 0) + data.get("output_tokens", 0)),
        }
        # 缓存相关
        cache_read = data.get("cache_read_input_tokens")
        cache_create = data.get("cache_creation_input_tokens")
        if cache_read is not None:
            result["prompt_cache_hit_tokens"] = cache_read
        if cache_create is not None:
            result["prompt_cache_miss_tokens"] = cache_create
        return result
    except Exception:
        return None


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider。

    消息格式双向转换，对上层暴露与 OpenAI 完全一致的接口。
    """

    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, timeout: float = 120.0):
        super().__init__(model, api_key, base_url, timeout)
        if not HAS_ANTHROPIC:
            raise RuntimeError("anthropic SDK 未安装，无法使用 Anthropic provider")
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    # -----------------------------------------------------------
    # 同步调用
    # -----------------------------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             **kwargs) -> dict:
        start = time.perf_counter()
        try:
            system, anthropic_msgs = _openai_messages_to_anthropic(messages)

            params: dict[str, Any] = {
                "model": self.model,
                "messages": anthropic_msgs,
                "max_tokens": kwargs.get("max_tokens", 4096),
            }
            if system:
                params["system"] = [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ]
            if tools:
                params["tools"] = _openai_tools_to_anthropic(tools)

            # 透传其他参数
            for k, v in kwargs.items():
                if k not in ("max_tokens",) and v is not None:
                    params[k] = v

            resp = self._client.messages.create(**params)

            content_blocks = resp.content if hasattr(resp, "content") else []
            text, tool_calls = _anthropic_content_to_openai(content_blocks)
            usage = _anthropic_usage_to_dict(getattr(resp, "usage", None))
            self.record_usage(usage, start)

            return {
                "content": text,
                "tool_calls": tool_calls,
                "usage": usage,
                "raw": resp,
            }
        except Exception as e:
            self.record_error()
            raise _classify_anthropic_error(e)

    # -----------------------------------------------------------
    # 流式调用
    # -----------------------------------------------------------
    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    **kwargs) -> Generator[tuple[str, Any, Any], None, None]:
        start = time.perf_counter()
        try:
            system, anthropic_msgs = _openai_messages_to_anthropic(messages)

            params: dict[str, Any] = {
                "model": self.model,
                "messages": anthropic_msgs,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "stream": True,
            }
            if system:
                params["system"] = [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ]
            if tools:
                params["tools"] = _openai_tools_to_anthropic(tools)

            for k, v in kwargs.items():
                if k not in ("max_tokens",) and v is not None:
                    params[k] = v

            with self._client.messages.stream(**params) as stream:
                text_parts: list[str] = []
                current_tool: dict | None = None
                tool_calls: list[dict] = []
                final_usage = None

                for event in stream:
                    etype = event.type if hasattr(event, "type") else ""

                    if etype == "content_block_delta":
                        delta = event.delta
                        dtype = delta.type if hasattr(delta, "type") else ""

                        if dtype == "text_delta":
                            txt = delta.text
                            text_parts.append(txt)
                            yield DELTA_CONTENT, txt, event

                        elif dtype == "input_json_delta":
                            # 工具调用参数增量
                            if current_tool is not None:
                                current_tool["args_parts"].append(delta.partial_json)
                                tc_dict = {
                                    "index": len(tool_calls),
                                    "id": current_tool["id"],
                                    "name": current_tool["name"],
                                    "arguments": "".join(current_tool["args_parts"]),
                                }
                                yield DELTA_TOOL_CALL, tc_dict, event

                    elif etype == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool = {
                                "id": block.id,
                                "name": block.name,
                                "args_parts": [],
                            }
                            tool_calls.append(current_tool)

                    elif etype == "content_block_stop":
                        if current_tool is not None:
                            current_tool = None

                    elif etype == "message_delta":
                        if hasattr(event, "usage") and event.usage:
                            final_usage = _anthropic_usage_to_dict(event.usage)
                            if final_usage:
                                yield DELTA_USAGE, final_usage, event

                    elif etype == "message_stop":
                        # 组装完整响应
                        import json as _j
                        full_tool_calls: list[dict] = []
                        for tc in tool_calls:
                            try:
                                args = _j.loads("".join(tc["args_parts"]) or "{}")
                            except Exception:
                                args = {"raw": "".join(tc["args_parts"])}
                            full_tool_calls.append({
                                "id": tc["id"],
                                "name": tc["name"],
                                "arguments": args,
                            })

                        full_resp = {
                            "content": "".join(text_parts),
                            "tool_calls": full_tool_calls,
                            "usage": final_usage,
                        }
                        self.record_usage(final_usage, start)
                        yield DELTA_DONE, full_resp, event
                        return

        except Exception as e:
            self.record_error()
            raise _classify_anthropic_error(e)
