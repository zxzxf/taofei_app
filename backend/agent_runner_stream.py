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
    tools_to_openai_functions,
)

MAX_STEPS = 25

# 复用 FC 模式的系统提示词
from agent_runner_fc import (
    FC_SYSTEM_PROMPT,
    _build_partial_report,
    _build_skill_prompts,
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
) -> None:
    """流式版本：在后台线程执行 FC agent，token 实时写入 delta_buffer。

    llm_stream_fn(messages, tools=None) -> generator
      生成器 yield (delta_type, delta_value):
        ("content", "token字符串")
        ("tool_call_delta", {index, id, name, arguments})
        ("done", response_obj)
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

    def push_delta(delta_type: str, delta: Any):
        """把一个 token delta 推送到缓冲区，触发事件通知。"""
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
        if notify_update:
            notify_update()

    update(status="running", mode="function_calling_streaming", delta_pointer=0)
    task_start_time = time.time()
    emit_log("INFO", f"[流式FC模式] Agent 任务开始：{user_request[:80]}...", task_id)

    # 构建工具列表
    skills = skills or []
    skill_tools = build_skill_tools(skills)
    all_tools = TOOLS + skill_tools
    openai_tools = tools_to_openai_functions(all_tools)

    # 构建系统提示
    system_content = FC_SYSTEM_PROMPT
    skill_prompt = _build_skill_prompts(skills)
    if skill_prompt:
        system_content += "\n\n## 已启用技能（请根据用户需求判断是否需要使用）\n" + skill_prompt

    # 初始化消息
    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": _build_user_content(user_request, images or [])},
    ]

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
            push_delta("step_start", {
                "step": step_idx + 1,
                "type": "thinking",
            })

            stream_generator = None
            try:
                stream_generator = llm_stream_fn(messages, tools=openai_tools)
            except Exception as exc:
                # 图片不支持的降级
                first_user = messages[1] if len(messages) > 1 else None
                has_image_blocks = (
                    isinstance(first_user, dict)
                    and isinstance(first_user.get("content"), list)
                    and any(isinstance(b, dict) and b.get("type") == "image_url" for b in first_user["content"])
                )
                if images and has_image_blocks:
                    emit_log("WARNING", f"当前模型不支持图片，已降级为纯文本重试：{exc}", task_id)
                    text_blocks = [
                        b for b in first_user["content"]
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    note = "\n\n（注意：当前模型不支持图片，已忽略用户附带的图片，请基于文字描述继续完成任务。）"
                    new_content = (text_blocks[0]["text"] if text_blocks else user_request) + note
                    messages[1] = {"role": "user", "content": new_content}
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
                            "arguments": args_dict,
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

            # 有工具调用 → 执行
            emit_log("INFO", f"[流式FC模式] 调用 {len(tool_calls)} 个工具：{[tc['function']['name'] for tc in tool_calls]}", task_id)

            # 构造 assistant 消息（带 tool_calls）
            assistant_msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            messages.append(assistant_msg)

            # 执行所有工具（暂时串行，第三阶段改为并行）
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                func_name = tc.get("function", {}).get("name", "")
                func_args = tc.get("function", {}).get("arguments", {})
                if isinstance(func_args, str):
                    try:
                        func_args = json.loads(func_args)
                    except Exception:
                        func_args = {}

                add_step({
                    "id": f"step-{step_idx + 1}-action-{func_name}",
                    "name": f"调用工具：{func_name}",
                    "status": "running",
                    "output": json.dumps(func_args, ensure_ascii=False),
                    "time": time.strftime("%H:%M:%S"),
                })
                emit_log("INFO", f"[流式FC模式] 工具 {func_name}({func_args})", task_id)

                # 工具开始执行事件
                push_delta("tool_start", {
                    "id": tc_id,
                    "name": func_name,
                    "args": func_args,
                })

                # 执行工具
                tool_result_str = execute_tool_fc(
                    func_name, workspace_path,
                    lambda msgs: None,  # 工具内不需要再调 llm（简化）
                    func_args, skills=skills,
                )

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

                # 构造 tool 消息回传
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result_str,
                })

                # 更新 timeline
                with task_lock:
                    timeline = task_store[task_id].get("timeline", [])
                    timeline.append({
                        "type": "command",
                        "name": func_name,
                        "args": func_args,
                        "result": tool_result_str,
                        "status": "error" if is_error else "done",
                        "time": time.strftime("%H:%M:%S"),
                        "elapsed": int(time.time() - task_start_time),
                    })
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

        # 推送完成事件
        push_delta("done", {
            "status": final_status,
        })

    except Exception as exc:
        err = str(exc)
        update(status="failed", error=err, current_step="失败")
        emit_log("ERROR", f"[流式FC模式] Agent 任务失败：{err}", task_id)
        push_delta("error", {"message": err})
