"""会话层（Session 化架构）。

跨请求持久的对话上下文：每个会话持有 OpenAI 兼容的原始 messages
（role/content/tool_calls/tool_call_id），LLM 每次调用直接复用，
不再把历史拼接成文本注入 user_request。
"""
from .session import ChatSession
from .manager import SessionManager, get_session_manager

__all__ = ["ChatSession", "SessionManager", "get_session_manager"]
