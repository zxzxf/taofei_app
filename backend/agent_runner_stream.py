"""流式版本的 Function Calling Agent Runner。

在后台线程中执行 agent 循环，边收 token 边写入 delta 缓冲区，
SSE/WebSocket 端点实时推送给前端，实现打字机效果。

与 agent_runner_fc.py 的关系：
- agent_runner_fc.py：非流式版本（请求-响应模式）
- 本文件：流式版本（token-by-token 推送）
- 两者共享相同的工具执行和消息处理逻辑
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from agent_tools import (
    TOOLS,
    build_skill_tools,
    execute_tool_fc,
    get_all_tools,
    tools_to_openai_functions,
)

MAX_STEPS = 25

# 复用 FC 模式的系统提示词
from agent_runner_fc import (
    FC_SYSTEM_PROMPT,
    _build_partial_report,
    _build_skill_prompts,
    _build_auto_skill_prompt,
    _build_user_content,
    _extract_content,
    _extract_tool_calls,
)


def run_agent_task_streaming(
    task_id: str,
    user_request: str,
    llm_stream_fn: Callable[[list[dict], list[dict] | None], Any],
    workspace_path: str | None,
    emit_log: Callable[..., Any],
    task_store: dict[str, dict],
    task_lock: threading.Lock,
    notify_update: Callable[[], None] | None = None,
    images: list[str] | None = None,
    skills: list[dict] | None = None,
    cancel_flag_getter: Callable[[], bool] | None = None,
    history_messages: list[dict] | None = None,
    messages_hook: Callable[[list[dict]], None] | None = None,
    tool_llm_call: Callable[..., Any] | None = None,
) -> None:
    """流式版本：在后台线程执行 FC agent，token 实时写入 delta_buffer。

    llm_stream_fn(messages, tools=None) -> generator
      生成器 yield (delta_type, delta_value):
        ("content", "token字符串")
        ("tool_call_delta", {index, id, name, arguments})
        ("done", response_obj)

    history_messages: Session 历史消息（不含 system/user），插在 system 与
        本轮 user 之间，让模型看到真实多轮上下文。
    messages_hook: 任务收尾时回调(最终完整 messages)，用于把本轮增量写回
        Session。仅在提供时启用。
    """

    def is_cancelled() -> bool:
        if cancel_flag_getter:
            try:
                return bool(cancel_flag_getter())
            except Exception:
                return False
        return False

    def update(**kwargs):
        with task_lock:
            if kwargs.get("status") in ("completed", "failed", "cancelled"):
                kwargs["completed_at"] = datetime.now(timezone.utc).astimezone().isoformat()
            task_store[task_id].update(kwargs)
        if notify_update:
            notify_update()

    def add_step(step: dict):
        with task_lock:
            task_store[task_id].setdefault("steps", []).append(step)
            task_store[task_id]["current_step"] = step["name"]
            task_store[task_id]["result"] = _build_partial_report(
                task_store[task_id]["steps"], user_request, status="running"
            )
        if notify_update:
            notify_update()

    # 节流：notify_update 每 50ms 最多触发一次，避免 token 级频繁 event.set + ws 广播
    _last_notify = [0.0]  # 用 list 实现闭包内可变变量

    def _throttled_notify():
        if not notify_update:
            return
        now = time.time()
        if now - _last_notify[0] >= 0.05:  # 50ms = ~20fps
            _last_notify[0] = now
            notify_update()

    def push_delta(delta_type: str, delta: Any):
        """把一个 token delta 推送到缓冲区，触发事件通知（节流）。"""
        with task_lock:
            buf = task_store[task_id].setdefault("delta_buffer", [])
            entry = {
                "type": delta_type,
                "delta": delta,
                "ts": time.time(),
            }
            buf.append(entry)
            # 限制缓冲区大小（保留最近 2000 条，防止内存泄漏）
            if len(buf) > 2000:
                task_store[task_id]["delta_buffer"] = buf[-2000:]
        _throttled_notify()

    update(status="running", mode="function_calling_streaming", delta_pointer=0)
    task_start_time = time.time()
    emit_log("INFO", f"[流式FC模式] Agent 任务开始：{user_request[:80]}...", task_id)

    # 构建工具列表
    skills = skills or []
    skill_tools = build_skill_tools(skills)
    all_tools = get_all_tools() + skill_tools
    openai_tools = tools_to_openai_functions(all_tools)

    # 构建系统提示
    system_content = FC_SYSTEM_PROMPT
    skill_prompt = _build_skill_prompts(skills)
    if skill_prompt:
        system_content += "\n\n## 已启用技能（请根据用户需求判断是否需要使用）\n" + skill_prompt

    # B6：自动知识技能按相关度动态注入
    auto_skill_prompt = _build_auto_skill_prompt(user_request)
    if auto_skill_prompt:
        system_content += "\n\n" + auto_skill_prompt

    # 初始化消息：system + (session 历史) + 本轮 user
    messages: list[dict] = [
        {"role": "system", "content": system_content},
    ]
    if history_messages:
        for hm in history_messages:
            if isinstance(hm, dict) and hm.get("role") != "system":
                messages.append(dict(hm))
    messages.append({
        "role": "user",
        "content": _build_user_content(user_request, images or []),
    })

    final_answer = ""
    near_limit_warned = False

    try:
        for step_idx in range(MAX_STEPS):
            if is_cancelled():
                emit_log("INFO", "任务已被用户取消", task_id)
                break

            # 显示思考中
            with task_lock:
                task_store[task_id]["current_step"] = f"思考第 {step_idx + 1} 步"
                _steps = task_store[task_id].get("steps", [])
                if _steps:
                    _rpt = _build_partial_report(_steps, user_request, status="running")
                    _rpt["summary"] = f"⏳ 正在思考第 {step_idx + 1} 步…"
                    task_store[task_id]["result"] = _rpt
            if notify_update:
                notify_update()
            emit_log("INFO", f"[流式FC模式] Agent 第 {step_idx + 1} 次调用模型", task_id)

            # 接近步数上限时提醒
            if step_idx >= MAX_STEPS - 3 and not near_limit_warned:
                messages.append({
                    "role": "user",
                    "content": "注意：你已接近最大步数限制，请根据已执行的工具调用和结果，直接给出最终答案，不要再调用新工具。",
                })
                near_limit_warned = True

            # 流式调用模型
            step_content_parts: list[str] = []
            step_tool_calls: list[dict] = []  # 最终的完整 tool_calls
            tool_call_states: dict[int, dict] = {}  # index -> {id, name, args_parts}

            # 推送 step_start 事件
            step_start_time = time.perf_counter()
            push_delta("step_start", {
                "step": step_idx + 1,
                "type": "thinking",
            })

            stream_generator = None
            try:
                stream_generator = llm_stream_fn(messages, tools=openai_tools)
            except Exception as exc:
                # 图片不支持的降级（定位本轮 user：messages 中最后一条 user）
                first_user = None
                for _m in reversed(messages):
                    if isinstance(_m, dict) and _m.get("role") == "user":
                        first_user = _m
                        break
                has_image_blocks = (
                    isinstance(first_user, dict)
                    and isinstance(first_user.get("content"), list)
                    and any(isinstance(b, dict) and b.get("type") == "image_url" for b in first_user["content"])
                )
                if images and has_image_blocks and first_user is not None:
                    emit_log("WARNING", f"当前模型不支持图片，已降级为纯文本重试：{exc}", task_id)
                    text_blocks = [
                        b for b in first_user["content"]
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    note = "\n\n（注意：当前模型不支持图片，已忽略用户附带的图片，请基于文字描述继续完成任务。）"
                    new_content = (text_blocks[0]["text"] if text_blocks else user_request) + note
                    first_user["content"] = new_content
                    stream_generator = llm_stream_fn(messages, tools=openai_tools)
                else:
                    raise

            final_response = None
            for delta_type, delta in stream_generator:
                if is_cancelled():
                    break

                if delta_type == "content":
                    # 文本 token
                    token = delta if isinstance(delta, str) else str(delta)
                    if token:
                        step_content_parts.append(token)
                        push_delta("content", token)

                elif delta_type == "tool_call_delta":
                    # 工具调用增量
                    tc_delta = delta if isinstance(delta, dict) else {}
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_call_states:
                        tool_call_states[idx] = {"id": "", "name": "", "args_parts": []}

                    if tc_delta.get("id"):
                        tool_call_states[idx]["id"] = tc_delta["id"]
                    if tc_delta.get("name"):
                        tool_call_states[idx]["name"] += tc_delta["name"]
                    if tc_delta.get("arguments"):
                        tool_call_states[idx]["args_parts"].append(tc_delta["arguments"])

                    push_delta("tool_call_delta", tc_delta)

                elif delta_type == "done":
                    final_response = delta
                    # done 不 push delta，前端用 step_end 标记
                    # 收集本步性能指标
                    step_perf = _extract_perf(final_response, step_start_time, len(step_content_parts))
                    with task_lock:
                        perf_list = task_store[task_id].setdefault("_perf_steps", [])
                        perf_list.append(step_perf)
                    push_delta("perf_step", step_perf)

            if is_cancelled():
                break

            # 从最终响应中提取完整内容和 tool_calls
            content = _extract_content(final_response) if final_response else "".join(step_content_parts)
            tool_calls = _extract_tool_calls(final_response) if final_response else []

            # 如果 final_response 没有 tool_calls 但我们从流式中收集到了
            if not tool_calls and tool_call_states:
                tool_calls = []
                for idx in sorted(tool_call_states.keys()):
                    state = tool_call_states[idx]
                    args_str = "".join(state["args_parts"])
                    args_dict = {}
                    if args_str.strip():
                        try:
                            args_dict = json.loads(args_str)
                        except Exception:
                            pass
                    tool_calls.append({
                        "id": state["id"] or f"call_{idx}",
                        "type": "function",
                        "function": {
                            "name": state["name"],
                            "arguments": args_str,
                        },
                    })

            # 添加思考步骤
            add_step({
                "id": f"step-{step_idx + 1}",
                "name": f"思考第 {step_idx + 1} 步",
                "status": "done",
                "output": content or "（调用工具中…）",
                "thinking": "",
                "time": time.strftime("%H:%M:%S"),
            })

            push_delta("step_end", {
                "step": step_idx + 1,
                "has_tool_calls": bool(tool_calls),
            })

            # 没有工具调用 → 任务完成
            if not tool_calls:
                final_answer = content
                # 把最终回答补成 assistant 消息，保证消息历史自洽（Session 回写需要）
                if content:
                    messages.append({"role": "assistant", "content": content})
                with task_lock:
                    timeline = task_store[task_id].get("timeline", [])
                    if content:
                        timeline.append({
                            "type": "thinking",
                            "content": content,
                            "time": time.strftime("%H:%M:%S"),
                            "elapsed": int(time.time() - task_start_time),
                        })
                    task_store[task_id]["timeline"] = timeline
                if notify_update:
                    notify_update()
                break

            # 有工具调用 → 并行执行
            emit_log("INFO", f"[流式FC模式] 并行调用 {len(tool_calls)} 个工具：{[tc['function']['name'] for tc in tool_calls]}", task_id)

            # 构造 assistant 消息（带 tool_calls）
            # 注意：发给 API 的 tool_calls.function.arguments 必须是 JSON 字符串，不能是 dict
            api_tool_calls = []
            for tc in tool_calls:
                func = tc.get("function", tc) if isinstance(tc, dict) else tc
                args = func.get("arguments", "") if isinstance(func, dict) else getattr(func, "arguments", "")
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                api_tool_calls.append({
                    "id": tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", ""),
                    "type": "function",
                    "function": {
                        "name": func.get("name", "") if isinstance(func, dict) else getattr(func, "name", ""),
                        "arguments": args,
                    },
                })
            assistant_msg = {
                "role": "assistant",
                "content": content if content else "",
                "tool_calls": api_tool_calls,
            }
            messages.append(assistant_msg)

            # 先解析所有 tool_calls 的参数
            parsed_tools = []
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                func_name = tc.get("function", {}).get("name", "")
                func_args = tc.get("function", {}).get("arguments", {})
                if isinstance(func_args, str):
                    try:
                        func_args = json.loads(func_args)
                    except Exception:
                        func_args = {}
                parsed_tools.append((tc_id, func_name, func_args))

            # 先批量推送 tool_start + 新增 timeline 项（让前端立即看到所有工具在跑）
            tool_indices = {}  # tc_id -> timeline index
            for i, (tc_id, func_name, func_args) in enumerate(parsed_tools):
                tool_indices[tc_id] = i
                add_step({
                    "id": f"step-{step_idx + 1}-action-{func_name}",
                    "name": f"调用工具：{func_name}",
                    "status": "running",
                    "output": json.dumps(func_args, ensure_ascii=False),
                    "time": time.strftime("%H:%M:%S"),
                })
                push_delta("tool_start", {
                    "id": tc_id,
                    "name": func_name,
                    "args": func_args,
                })
                emit_log("INFO", f"[流式FC模式] 工具 {func_name}({func_args})", task_id)

            # 预占 timeline 位置
            with task_lock:
                timeline = task_store[task_id].get("timeline", [])
                for tc_id, func_name, func_args in parsed_tools:
                    timeline.append({
                        "type": "command",
                        "name": func_name,
                        "args": func_args,
                        "result": "",
                        "status": "running",
                        "time": time.strftime("%H:%M:%S"),
                        "elapsed": 0,
                    })
                task_store[task_id]["timeline"] = timeline
            if notify_update:
                notify_update()

            # 并行执行所有工具
            import concurrent.futures

            def _run_single_tool(tc_item):
                tc_id, func_name, func_args = tc_item

                # 每个工具独立的流式输出回调（线程安全：通过 push_delta 发送）
                def _tool_line_cb(stream_name, line_text):
                    push_delta("tool_output_line", {
                        "id": tc_id,
                        "name": func_name,
                        "stream": stream_name,
                        "line": line_text,
                    })

                try:
                    tool_result_str = execute_tool_fc(
                        func_name, workspace_path,
                        # 工具内嵌 LLM（ask_llm / delegate_tasks 需要）；默认禁用
                        tool_llm_call if tool_llm_call is not None else (lambda msgs: None),
                        func_args, skills=skills,
                        tool_line_cb=_tool_line_cb,
                    )
                except Exception as exc:
                    tool_result_str = f"Error: {exc}"

                return tc_id, func_name, func_args, tool_result_str

            tool_results = {}
            max_workers = min(max(len(parsed_tools), 1), 8)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(_run_single_tool, item): item[0] for item in parsed_tools}
                for future in concurrent.futures.as_completed(future_map):
                    tc_id, func_name, func_args, result_str = future.result()
                    tool_results[tc_id] = (func_name, func_args, result_str)

            # 按原始 tool_calls 顺序组装结果（保证消息顺序一致）
            for tc_id, func_name, func_args in parsed_tools:
                _, _, tool_result_str = tool_results.get(tc_id, (func_name, func_args, "Error: 工具执行失败"))
                is_error = tool_result_str.startswith("Error:")

                add_step({
                    "id": f"step-{step_idx + 1}-observation-{func_name}",
                    "name": f"工具结果：{func_name}",
                    "status": "error" if is_error else "done",
                    "output": tool_result_str,
                    "time": time.strftime("%H:%M:%S"),
                })
                emit_log("INFO", f"[流式FC模式] 工具 {func_name} 返回：{tool_result_str[:200]}", task_id)

                # 工具完成事件
                push_delta("tool_end", {
                    "id": tc_id,
                    "name": func_name,
                    "status": "error" if is_error else "done",
                    "output": tool_result_str[:500],  # 预览，完整的看 steps
                })

                # 构造 tool 消息回传（按原始顺序）
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result_str,
                })

                # 更新 timeline 对应项
                idx = tool_indices[tc_id]
                with task_lock:
                    timeline = task_store[task_id].get("timeline", [])
                    # 找到对应的 command 项（按顺序偏移）
                    # timeline 是按顺序追加的，tool_indices 存的是原始顺序索引
                    # 需要从 timeline 末尾数 len(parsed_tools) 个里面找
                    base_offset = len(timeline) - len(parsed_tools)
                    target_idx = base_offset + idx
                    if 0 <= target_idx < len(timeline) and timeline[target_idx]["type"] == "command":
                        timeline[target_idx]["result"] = tool_result_str
                        timeline[target_idx]["status"] = "error" if is_error else "done"
                        timeline[target_idx]["elapsed"] = int(time.time() - task_start_time)
                    task_store[task_id]["timeline"] = timeline

            if notify_update:
                notify_update()

        else:
            # 步数耗尽
            emit_log("WARNING", "[流式FC模式] Agent 步数耗尽，强制生成总结报告", task_id)
            summary_messages = messages + [
                {
                    "role": "user",
                    "content": "任务步数即将耗尽。请基于以上所有工具调用和结果，直接输出最终总结。",
                },
            ]
            try:
                # 最后一次总结用非流式
                from agent_runner_fc import run_agent_task_fc
                # 简单起见，直接调 llm
                final_reply = None
                for dt, dv in llm_stream_fn(summary_messages, tools=[]):
                    if dt == "done":
                        final_reply = dv
                        break
                final_answer = _extract_content(final_reply) if final_reply else ""
            except Exception as exc:
                final_answer = f"任务步数已达上限，且生成总结时出错：{exc}。请尝试把需求拆小或增加步数限制。"

        # 完成
        steps = task_store[task_id].get("steps", [])
        cancelled = is_cancelled()
        final_status = "cancelled" if cancelled else "completed"
        computed_report = _build_partial_report(steps, user_request, status=final_status)

        if not task_store[task_id].get("thinking_duration"):
            with task_lock:
                task_store[task_id]["thinking_duration"] = max(1, int(time.time() - task_start_time))

        if cancelled:
            final_report = computed_report
            final_report["title"] = f"已取消：{user_request[:30]}…"
            final_report["summary"] = f"任务已被用户取消，已执行 {len(steps)} 步。"
            update(status="cancelled", result=final_report, current_step="已取消")
            emit_log("INFO", "Agent 任务已取消", task_id)
        else:
            # 尝试提取 report JSON
            report_data = None
            if isinstance(final_answer, str):
                stripped = final_answer.strip()
                if stripped.startswith("{") and '"type"' in stripped and '"report"' in stripped:
                    try:
                        import re as _re
                        m = _re.search(r"\{[^{}]*\"type\"\s*:\s*\"report\"[^{}]*\}", stripped, _re.DOTALL)
                        if m:
                            report_data = json.loads(m.group(0))
                    except Exception:
                        pass

            if report_data and isinstance(report_data, dict) and report_data.get("type") == "report":
                report_data["status"] = "completed"
                report_data["steps"] = steps
                report_data["duration"] = computed_report.get("duration", "进行中")
                update(status="completed", result=report_data, current_step="完成")
                emit_log("INFO", "Agent 任务完成（report 格式）", task_id)
            else:
                final_report = computed_report
                final_report["title"] = f"已完成：{user_request[:30]}…"
                answer_text = str(final_answer) if final_answer else "Agent 已完成任务。"
                short_summary = answer_text[:80].strip() + ("…" if len(answer_text) > 80 else "")
                final_report["summary"] = short_summary
                final_report["sections"] = [{
                    "heading": "答案",
                    "items": [{"type": "text", "content": answer_text}],
                }]
                update(status="completed", result=final_report, current_step="完成")
                emit_log("INFO", "Agent 任务完成", task_id)

        # 收尾：把本轮完整消息回写给 Session（若提供 hook）
        try:
            if messages_hook:
                messages_hook(messages)
        except Exception as _hook_exc:
            emit_log("WARNING", f"会话消息回写失败：{_hook_exc}", task_id)

        # 推送完成事件
        push_delta("done", {
            "status": final_status,
        })

    except Exception as exc:
        err = str(exc)
        update(status="failed", error=err, current_step="失败")
        emit_log("ERROR", f"[流式FC模式] Agent 任务失败：{err}", task_id)
        try:
            if messages_hook:
                messages_hook(messages)
        except Exception:
            pass
        push_delta("error", {"message": err})


# ------------------------------------------------------------------
# 性能指标提取
# ------------------------------------------------------------------
def _extract_perf(final_response, step_start_time, token_count: int) -> dict:
    """从 LLM 最终响应中提取本步性能指标。

    返回：{
        first_token_ms: 首字延迟(ms),  # 流式中从 step_start 到第一个 content token
        total_ms: 本步总耗时(ms),
        completion_tokens: 输出 token 数,
        prompt_tokens: 输入 token 数,
        prompt_cache_hit_tokens: 前缀缓存命中,
        prompt_cache_miss_tokens: 前缀缓存未命中,
        cache_hit_ratio: 缓存命中率(0-1),
        tokens_per_second: 输出速度(tokens/s),
        has_tool_call: 是否为工具调用步,
    }
    """
    elapsed = time.perf_counter() - step_start_time
    total_ms = int(elapsed * 1000)

    usage = None
    has_tool_call = False

    # 从 final_response 中提取 usage
    if final_response is not None:
        # openai SDK ChatCompletion 对象
        if hasattr(final_response, "usage") and final_response.usage is not None:
            try:
                if hasattr(final_response.usage, "model_dump"):
                    usage = final_response.usage.model_dump()
                elif hasattr(final_response.usage, "dict"):
                    usage = final_response.usage.dict()
                else:
                    usage = dict(final_response.usage)
            except Exception:
                usage = None
        # 或者是 dict
        elif isinstance(final_response, dict):
            usage = final_response.get("usage")

        # 判断是否有工具调用
        try:
            msg = final_response.choices[0].message if hasattr(final_response, "choices") else None
            if msg and hasattr(msg, "tool_calls") and msg.tool_calls:
                has_tool_call = True
        except Exception:
            pass

    prompt_tokens = usage.get("prompt_tokens") if usage else None
    completion_tokens = usage.get("completion_tokens") if usage else None
    cache_hit = usage.get("prompt_cache_hit_tokens") if usage else None
    cache_miss = usage.get("prompt_cache_miss_tokens") if usage else None

    cache_hit_ratio = None
    if cache_hit is not None and cache_miss is not None and (cache_hit + cache_miss) > 0:
        cache_hit_ratio = round(cache_hit / (cache_hit + cache_miss), 3)

    # 计算输出速度（用 completion_tokens 更准，没有就用流式收集的 token_count 估算）
    tps = None
    ct = completion_tokens if completion_tokens else token_count
    if ct and elapsed > 0:
        tps = round(ct / elapsed, 1)

    return {
        "total_ms": total_ms,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": cache_miss,
        "cache_hit_ratio": cache_hit_ratio,
        "tokens_per_second": tps,
        "has_tool_call": has_tool_call,
    }
