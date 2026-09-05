"""LLM 提供商包（阶段 6：多提供商 + 故障转移）。

架构
----
- ``base.BaseProvider``：Provider 基类（统一接口 + 错误分类 + 统计）
- ``openai_compat.OpenAICompatProvider``：OpenAI 兼容端点（DeepSeek/OpenAI/智谱/本地...）
- ``anthropic.AnthropicProvider``：Anthropic Claude（消息格式双向转换）
- ``fallback_chain.FallbackChain``：故障转移链（主挂了自动切备用）
- ``registry.ProviderRegistry``：提供商注册表（自动探测 + 预设管理）

向后兼容
--------
旧代码 ``from providers import OpenAICompatLLM`` 继续可用。
"""
from .base import (
    BaseProvider,
    ProviderError,
    AuthError,
    RateLimitError,
    ServerError,
    BadRequestError,
    ContextLengthError,
)
from .openai_compat import OpenAICompatProvider, OpenAICompatLLM, format_usage, usage_to_dict
from .fallback_chain import FallbackChain
from .registry import ProviderRegistry, ProviderConfig

__all__ = [
    "BaseProvider",
    "ProviderError",
    "AuthError",
    "RateLimitError",
    "ServerError",
    "BadRequestError",
    "ContextLengthError",
    "OpenAICompatProvider",
    "OpenAICompatLLM",
    "FallbackChain",
    "ProviderRegistry",
    "ProviderConfig",
    "format_usage",
    "usage_to_dict",
]
