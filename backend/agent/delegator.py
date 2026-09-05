# -*- coding: utf-8 -*-
"""delegator.py —— 自包含的子任务并行执行器（Hermes delegate_task 风格）。

把一批相互独立的子任务（subtask）用 ``concurrent.futures.ThreadPoolExecutor`` 并行执行，
每个子任务在**完全隔离**的消息上下文里独立跑 function-calling 循环：

    system(中文子代理提示词) → user(request)
        → [ assistant(tool_calls) → tool(结果) × N ] × 轮
        → 无 tool_calls 的最终文本 = answer

设计要点
--------
- **完全自包含**：本模块不 import 本项目任何业务模块（main / agent_runner* /
  agent_tools 均不引用），所有依赖（``llm_call``、``execute_tool``、
  ``tool_schemas``）全部通过参数注入，可独立测试、独立复用。
- **上下文隔离**：messages 列表在每个子任务内部独立构造、独立演进，
  delegator 自身不持有任何跨任务共享的可变状态，因此多个线程安全并发。
- **线程安全**：``llm_call`` 由调用方保证线程安全（本项目 main.py 的 llm_call
  每次调用内部自带独立线程 + 超时控制，天然线程安全），这里只负责"每个子任务
  在自己的线程里顺序调用"，绝不跨线程共享消息对象。
- **错误隔离**：单个子任务内的任何异常（含 llm_call 异常、execute_tool 抛异常、
  步数耗尽）只让该子任务标记 ``status="failed"`` + ``error`` 记录原因，
  不影响其它子任务；``delegate_tasks`` 整体永不抛异常。

返回值
------
``{"results": [{"id", "status", "answer", "error", "duration_ms", "steps"}, ...]}``
其中 results 的顺序与入参 specs 的顺序一致。status 取值 ``"completed"`` /
``"failed"``；answer 为最终文本；error 为空字符串表示成功，否则为异常信息
（真实 execute_tool 以 dict{error} 形式报告的工具错误不会让任务 failed，
而是把错误文本交还给模型继续推理——只有真正抛出异常/步数耗尽才判 failed）。
"""

from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional, Sequence

# 单条工具结果回填给模型前最多保留的字符数（防止长输出撑爆上下文/token 预算）。
# 工具自身一般已做截断，这里只是最后一道防线。
_MAX_TOOL_RESULT_CHARS: int = 60000

# 类型别名：llm_call(messages, tools=None) -> 响应对象
# （本项目里 tools 为 None 时返回 str；带 tools 时返回 openai ChatCompletion 形态对象）
LLMCallFn = Callable[[list[dict], Optional[list[dict]]], Any]
# execute_tool(name, workspace_path, llm_call, args) -> dict{"observation","error"} 或 str
ExecuteToolFn = Callable[..., Any]


# --------------------------------------------------------------------------
# 模块级：默认子代理 system 提示词
# --------------------------------------------------------------------------
def build_system_prompt() -> str:
    """构造子任务执行代理的默认 system 提示词（中文 function-calling 风格）。

    每个子任务都会用它的返回值作为 messages[0]（完全独立的新字符串）。
    """
    return (
        "你是子任务执行代理，可调用工具来完成任务。\n"
        "请遵守以下规则：\n"
        "1. 需要查询或执行外部操作时，先以 function call 调用可用工具；"
        "工具结果会以 role=tool 消息返回给你；\n"
        "2. 每次回复只做必要的工具调用，避免无意义地重复调用同一工具；\n"
        "3. 当所有必要信息都已获取、不再需要调用工具时，直接输出最终结论；\n"
        "4. 完成后用中文给出简洁结论（通常 2~5 句话即可），不要复述中间过程。"
    )


# --------------------------------------------------------------------------
# 响应解析：兼容 openai ChatCompletion 形态（对象或 dict 均可）
#   - 对象：response.message.content / response.message.tool_calls
#           tool_call.id / tool_call.function.name / tool_call.function.arguments(str)
#   - dict ：response["message"]["tool_calls"]（少数实现/回放场景）
# --------------------------------------------------------------------------
def _get(obj: Any, name: str, default: Any = None) -> Any:
    """同时兼容对象属性与 dict 键的读取（不抛异常）。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_message(response: Any) -> Any:
    """从响应里取出 message（兼容 .message 与 .choices[0].message 两种位置）。"""
    if response is None:
        return None
    msg = _get(response, "message")
    if msg is None:
        choices = _get(response, "choices") or []
        if choices:
            msg = _get(choices[0], "message")
    return msg


def _content_of(message: Any) -> str:
    """取 message 的纯文本内容：兼容 None、str、多模态块列表（只拼 text 块）。"""
    if message is None:
        return ""
    content = _get(message, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # 多模态 content 块（[{type:text/text}...]）
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)
    return str(content)


def _extract_tool_calls(response: Any) -> list[dict]:
    """把响应里的 tool_calls 归一化为 [{id, name, arguments(str)}, ...]。

    归一化后的 ``arguments`` 一定是 JSON 字符串（dict 会被 json.dumps），
    与 OpenAI 协议要求的 wire 格式一致，方便原样回填 assistant 消息。
    """
    msg = _extract_message(response)
    if msg is None:
        return []
    tcs = _get(msg, "tool_calls")
    if not tcs:
        return []
    out: list[dict] = []
    for tc in tcs:
        if tc is None:
            continue
        func = _get(tc, "function")
        name = _get(func, "name", "") if func is not None else ""
        arguments = _get(func, "arguments", "") if func is not None else ""
        if isinstance(arguments, dict):  # 某些实现直接给 dict → 序列化成 JSON 字符串
            arguments = json.dumps(arguments, ensure_ascii=False)
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False)
        out.append(
            {
                "id": str(_get(tc, "id", "") or ""),
                "name": str(name or ""),
                "arguments": arguments,
            }
        )
    return out


# --------------------------------------------------------------------------
# 工具结果归一化
# --------------------------------------------------------------------------
def _tool_result_to_text(raw: Any) -> str:
    """把 execute_tool 的返回值归一化为字符串（回填给 role=tool 消息）。

    - 真实 execute_tool（agent_tools.execute_tool）返回 ``dict``：
      约定含 ``observation`` 键；``error`` 非空表示执行失败——此时**把 error
      文本作为工具结果返回给模型**（与主 agent 的 FC 循环约定一致）；
    - 冒烟测试/自定义 execute_tool 可能直接返回 str —— 同样兼容。
    """
    if raw is None:
        return "（工具无返回内容）"
    if isinstance(raw, dict):
        error = raw.get("error")
        if error:  # error 非空 → 错误文本交给模型继续推理（不算任务失败）
            return str(error)
        observation = raw.get("observation")
        if observation is not None:
            return str(observation)
        return json.dumps(raw, ensure_ascii=False) if raw else "（工具无返回内容）"
    return raw if isinstance(raw, str) else str(raw)


# --------------------------------------------------------------------------
# 单个子任务：在自己（调用线程）内跑完整的 function-calling 循环
# --------------------------------------------------------------------------
def _run_subtask(
    spec: dict,
    llm_call: LLMCallFn,
    tool_schemas: list[dict],
    execute_tool: ExecuteToolFn,
    workspace_path: Optional[str],
    max_steps: int,
) -> dict:
    """执行单个子任务，返回一条 results 记录；本函数绝不向外抛异常。

    每个子任务的 messages 上下文在函数内部从零构造、随循环演进，
    不与其它子任务共享任何对象 —— 这就是"完全隔离"的落点。
    """
    task_id = str(spec.get("id", "?"))
    request = spec.get("request", "")
    if not isinstance(request, str):
        request = str(request)
    started = time.perf_counter()
    steps = 0  # 已执行的 llm 轮数

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        # —— 完全隔离的消息上下文 ——
        messages: list[dict] = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": request},
        ]

        final_text = ""
        exhausted = False  # True = 跑满 max_steps 轮仍未产出结论
        for step in range(1, max_steps + 1):
            steps = step
            # 每轮一次模型调用。tools 每次传同一份 tool_schemas（只读共享，安全）。
            # 注意：llm_call 必须由调用方保证线程安全；本模块只在本线程内顺序调用。
            response = llm_call(messages, tools=tool_schemas)

            # 容错：个别 llm_call 在无工具可用时直接返回 str —— 视为最终文本
            if isinstance(response, str):
                final_text = response
                break

            tool_calls = _extract_tool_calls(response)
            content = _content_of(_extract_message(response))
            if not tool_calls:
                # 模型不再调用工具 → 本轮文本即为最终结论
                final_text = content
                break

            # 有工具调用：先把 assistant 消息（含 tool_calls，wire 格式）写进历史
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],  # 必须是 JSON 字符串
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # 逐条执行工具，结果以 role=tool（带 tool_call_id）消息回填，保持协议自洽。
            # 每轮里的工具调用按顺序执行（工具自身一般无状态，顺序执行足够）。
            for tc in tool_calls:
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except Exception:
                    args = {}  # 参数 JSON 损坏 → 空参执行，交由工具侧自行报错
                if not isinstance(args, dict):
                    args = {}
                try:
                    raw = execute_tool(
                        name=tc["name"],
                        workspace_path=workspace_path,
                        llm_call=None,  # 子代理不向工具注入内层 LLM（如需可后续扩展）
                        args=args,
                    )
                except Exception as exc:
                    # 工具真正抛异常 → 让本子任务失败（由外层兜底标记 failed）；
                    # 真实 execute_tool 通常不抛而返回 dict{error}，走上面的归一化路径。
                    raise RuntimeError(
                        f"子任务 {task_id} 调用工具 {tc['name']!r} 异常："
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                text = _tool_result_to_text(raw)
                if len(text) > _MAX_TOOL_RESULT_CHARS:
                    text = (
                        text[:_MAX_TOOL_RESULT_CHARS]
                        + f"\n…（工具结果过长，已截断至 {_MAX_TOOL_RESULT_CHARS} 字符）"
                    )
                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": text}
                )
        else:
            # for 循环正常结束（未被 break）= 跑满 max_steps 轮仍在调工具
            exhausted = True

        if exhausted:
            raise RuntimeError(
                f"子任务 {task_id} 达到最大步数限制（max_steps={max_steps}）仍未产出最终结论"
            )

        answer = final_text.strip() if (final_text or "").strip() else "（子代理未返回文本结论）"
        return {
            "id": task_id,
            "status": "completed",
            "answer": answer,
            "error": "",
            "duration_ms": _elapsed_ms(),
            "steps": steps,
        }
    except Exception as exc:  # 单任务异常：记录 error，绝不外泄影响其它子任务
        return {
            "id": task_id,
            "status": "failed",
            "answer": "",
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": _elapsed_ms(),
            "steps": steps,
        }


# --------------------------------------------------------------------------
# 对外主入口
# --------------------------------------------------------------------------
def delegate_tasks(
    specs: list[dict],
    llm_call: LLMCallFn,
    tool_schemas: list[dict],
    execute_tool: ExecuteToolFn,
    workspace_path: Optional[str] = None,
    max_workers: int = 4,
    max_steps: int = 6,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> dict:
    """并行执行一批相互独立的子任务（Hermes delegate_task 风格）。

    参数
    ----
    specs : list[dict]
        每个元素形如 ``{"id": str, "request": str}``。
    llm_call : callable
        ``llm_call(messages, tools=tool_schemas) -> 响应对象``（openai
        ChatCompletion 形态：``.message.content`` / ``.message.tool_calls``；
        tool_call 有 ``.id`` / ``.function.name`` / ``.function.arguments``）。
        调用方必须保证线程安全（本项目 main.py 的 llm_call 已满足）。
    tool_schemas : list[dict]
        OpenAI function 格式工具列表（type/function.name/description/parameters），
        只读共享，不会在本模块内被修改。
    execute_tool : callable
        ``execute_tool(name, workspace_path, llm_call=None, args=dict)``，
        返回 ``dict{"observation": str, "error": str}``（或直接返回 str 亦可）。
        真实实现即 agent_tools.execute_tool —— 本模块不 import 它，只按参数约定调用。
    workspace_path : str | None
        透传给 execute_tool 的工作区路径（可为 None）。
    max_workers : int
        并行线程数（ThreadPoolExecutor）。<=0 时按 1 处理。
    max_steps : int
        每个子任务最多执行的 llm 轮数（function-calling 循环轮数上限）。
        <=0 时按默认 6 处理。
    progress_cb : callable | None
        进度回调，子任务状态变化时调用，参数为 dict：
        ``{"type": "subtask_update", "id": str, "request": str,
        "status": "running"|"completed"|"failed",
        "answer": str, "error": str, "duration_ms": int, "steps": int}``
        用于前端实时渲染并行子任务卡片。

    返回
    ----
    dict: ``{"results": [{"id", "status", "answer", "error", "duration_ms",
    "steps"}, ...]}``，顺序与 specs 一致；单任务异常不会影响其它任务，
    本函数在任何情况下都不抛异常。
    """
    # 入参防御性归一化（保证永不抛异常）
    try:
        specs = list(specs) if specs else []
    except Exception:
        specs = []
    if max_workers <= 0:
        max_workers = 1
    if max_steps <= 0:
        max_steps = 6
    if not specs:
        return {"results": []}

    # 按 id(spec) 收集完成结果，最后按输入顺序重排，保证返回顺序稳定
    ordered: dict[int, dict] = {}

    def _emit(event: dict) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(event)
        except Exception:
            pass  # 进度回调失败不影响主流程

    try:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="delegate") as pool:
            future_to_spec = {
                pool.submit(
                    _run_subtask,
                    spec,
                    llm_call,
                    tool_schemas,
                    execute_tool,
                    workspace_path,
                    max_steps,
                ): spec
                for spec in specs
            }
            # 启动时发送 running 通知
            for spec in specs:
                _emit({
                    "type": "subtask_update",
                    "id": str(spec.get("id", "?")),
                    "request": str(spec.get("request", "")),
                    "status": "running",
                    "answer": "",
                    "error": "",
                    "duration_ms": 0,
                    "steps": 0,
                })
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                try:
                    result = future.result()  # _run_subtask 不抛，双保险
                except Exception as exc:  # pragma: no cover —— 理论不可达
                    result = {
                        "id": str(spec.get("id", "?")),
                        "status": "failed",
                        "answer": "",
                        "error": f"{type(exc).__name__}: {exc}",
                        "duration_ms": 0,
                        "steps": 0,
                    }
                ordered[id(spec)] = result
                # 完成时发送最终状态通知（带上 request 方便前端展示）
                _emit({
                    "type": "subtask_update",
                    "id": result["id"],
                    "request": str(spec.get("request", "")),
                    "status": result["status"],
                    "answer": result.get("answer", ""),
                    "error": result.get("error", ""),
                    "duration_ms": result.get("duration_ms", 0),
                    "steps": result.get("steps", 0),
                })
        results = [ordered[id(spec)] for spec in specs]
    except Exception as exc:
        # 极端情况（如线程池创建失败）：整体降级为逐条失败记录，绝不外抛
        traceback.print_exc()
        results = [
            {
                "id": str(spec.get("id", "?")),
                "status": "failed",
                "answer": "",
                "error": f"delegate_tasks 整体执行异常: {type(exc).__name__}: {exc}",
                "duration_ms": 0,
                "steps": 0,
            }
            for spec in specs
        ]
    return {"results": results}
