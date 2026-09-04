# -*- coding: utf-8 -*-
"""backend/agent —— 子代理（subagent）相关功能包。

当前只包含一个自包含的「子任务并行执行器」delegator：
把一批相互独立的子任务并行跑在多个线程里，每个子任务拥有完全隔离的
消息上下文与 function-calling 循环，单任务失败互不影响。
"""
from .delegator import build_system_prompt, delegate_tasks

__all__ = ["delegate_tasks", "build_system_prompt"]
