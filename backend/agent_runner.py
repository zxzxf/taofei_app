"""ReAct Agent 执行器。

让大模型按 "Thought / Action / Action Input / Observation" 格式循环输出，
直到产出 "Final Answer"。执行过程写入 _tasks 状态，前端通过 /api/status/{task_id} 轮询。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Callable

from agent_tools import TOOLS, execute_tool

MAX_STEPS = 10


REACT_SYSTEM_PROMPT = """你是一个能调用工具完成复杂任务的 Agent。请严格按以下 ReAct 格式思考并行动：

可用工具：
{tools_desc}

输出格式要求（必须严格遵循）：
Thought: 你对当前任务的分析和下一步计划
Action: 工具名称（必须是上面列出的工具之一）
Action Input: <JSON 对象，参数按工具定义填写>
Observation: <工具执行结果会自动填入，你不需要写>

当任务完成时，输出：
Final Answer: 给用户的最终答案。如果任务是排查、诊断、总结类任务，Final Answer 请使用如下 JSON 报告格式（不要加 markdown 代码块，直接输出 JSON 字符串）：
{{
  "type": "report",
  "title": "问题找到了：...",
  "status": "completed",
  "summary": "排查结果...",
  "sections": [
    {{"heading": "我已做的处理", "items": ["步骤1...", "步骤2..."]}},
    {{"heading": "验证结果", "items": ["/api/health ✓", "/api/chat ✓"]}}
  ]
}}

规则：
1. 每次回复只能包含一轮 Thought + Action + Action Input，或最终的 Final Answer。
2. Action Input 必须是合法 JSON，不要加 markdown 代码块。
3. 如果用户请求涉及项目文件，优先使用 list_directory 和 read_file 查看文件。
4. 如需创建或修改文件，使用 write_file。
5. 如需计算或运行脚本，使用 run_python_code。
6. 如果需要模型帮你总结、改写、分析，使用 ask_llm。
"""


def _format_tools() -> str:
    lines = []
    for t in TOOLS:
        lines.append(f"- {t['name']}: {t['description']}")
        lines.append(f"  参数: {json.dumps(t['parameters'], ensure_ascii=False)}")
    return "\n".join(lines)


def _parse_action(text: str) -> tuple[str, dict] | None:
    """从模型输出中解析 Action 和 Action Input。"""
    action_match = re.search(r"Action:\s*(\S+)", text)
    if not action_match:
        return None
    action_name = action_match.group(1).strip()
    input_match = re.search(r"Action Input:\s*(\{.*?\})\s*(?:Observation:|$)", text, re.DOTALL)
    if input_match:
        try:
            args = json.loads(input_match.group(1))
        except Exception:
            args = {}
    else:
        args = {}
    return action_name, args


def _has_final_answer(text: str) -> bool:
    return "Final Answer:" in text


def _extract_final_answer(text: str) -> str:
    match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _build_partial_report(steps: list[dict], user_request: str, status: str = "running") -> dict:
    """根据当前步骤生成部分报告，供前端伪流式展示。"""
    items = []
    for st in steps:
        icon = "⏳" if st.get("status") == "running" else "✅" if st.get("status") == "done" else "❌"
        name = st.get("name", "")
        # 跳过中间思考细节，只展示动作和结果
        if "思考" in name and not name.endswith("步"):
            continue
        items.append(f"{icon} {name}")
    duration = "进行中"
    if steps:
        try:
            first = steps[0].get("time", "")
            last = steps[-1].get("time", "")
            if first and last:
                fmt = "%H:%M:%S"
                t1 = time.strptime(first, fmt)
                t2 = time.strptime(last, fmt)
                secs = (time.mktime(t2) - time.mktime(t1))
                duration = f"{int(secs // 60)}m{int(secs % 60)}s"
        except Exception:
            pass
    return {
        "type": "report",
        "title": f"正在处理：{user_request[:30]}…",
        "status": status,
        "duration": duration,
        "summary": f"已执行 {len(steps)} 步，最新动作：{steps[-1].get('name', '') if steps else '准备中'}。",
        "sections": [
            {"heading": "执行步骤", "items": items or ["准备开始…"]},
        ],
    }


def _is_report_json(text: str) -> bool:
    return text.strip().startswith("{") and '"type"' in text and '"report"' in text


def run_agent_task(
    task_id: str,
    user_request: str,
    llm_call: Callable[[list[dict]], str],
    workspace_path: str | None,
    emit_log: Callable[..., Any],
    task_store: dict[str, dict],
    task_lock: threading.Lock,
    notify_update: Callable[[], None] | None = None,
) -> None:
    """在后台线程中执行 ReAct Agent。"""

    def update(**kwargs):
        with task_lock:
            task_store[task_id].update(kwargs)
        if notify_update:
            notify_update()

    def add_step(step: dict):
        with task_lock:
            task_store[task_id].setdefault("steps", []).append(step)
            task_store[task_id]["current_step"] = step["name"]
            # 每完成一步都刷新部分报告，前端轮询/SSE 时能看到逐步成形
            task_store[task_id]["result"] = _build_partial_report(
                task_store[task_id]["steps"], user_request, status="running"
            )
        if notify_update:
            notify_update()

    update(status="running")
    emit_log("INFO", f"Agent 任务开始：{user_request[:80]}...", task_id)

    messages: list[dict] = [
        {"role": "system", "content": REACT_SYSTEM_PROMPT.format(tools_desc=_format_tools())},
        {"role": "user", "content": user_request},
    ]

    final_answer = ""
    try:
        for step_idx in range(MAX_STEPS):
            update(current_step=f"思考第 {step_idx + 1} 步")
            emit_log("INFO", f"Agent 第 {step_idx + 1} 次调用模型", task_id)

            reply = llm_call(messages)
            add_step({
                "id": f"step-{step_idx + 1}",
                "name": f"思考第 {step_idx + 1} 步",
                "status": "done",
                "output": reply,
                "time": time.strftime("%H:%M:%S"),
            })

            if _has_final_answer(reply):
                final_answer = _extract_final_answer(reply)
                # 如果最终答案是 JSON 报告，直接作为结构化结果；否则用普通文本
                if _is_report_json(final_answer):
                    try:
                        final_answer = json.loads(final_answer)
                    except Exception:
                        pass
                break

            parsed = _parse_action(reply)
            if not parsed:
                # 让模型重试一次
                retry_msg = (
                    "你刚才的输出格式不正确。请严格按以下格式输出：\n"
                    "Thought: ...\nAction: ...\nAction Input: {...}\n"
                    "如果已完成任务，请输出 Final Answer: ..."
                )
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": retry_msg})
                add_step({
                    "id": f"step-{step_idx + 1}-retry",
                    "name": "格式重试",
                    "status": "done",
                    "output": "模型未按 ReAct 格式输出，已提示重试",
                    "time": time.strftime("%H:%M:%S"),
                })
                continue

            action_name, args = parsed
            add_step({
                "id": f"step-{step_idx + 1}-action",
                "name": f"调用工具：{action_name}",
                "status": "running",
                "output": json.dumps(args, ensure_ascii=False),
                "time": time.strftime("%H:%M:%S"),
            })
            emit_log("INFO", f"调用工具 {action_name}({args})", task_id)

            tool_result = execute_tool(action_name, workspace_path, llm_call, args)
            observation = tool_result.get("observation", "")
            error = tool_result.get("error", "")

            if error:
                observation_text = f"{observation}\n错误：{error}".strip() if observation else error
                status = "error"
            else:
                observation_text = observation or "（无返回）"
                status = "done"

            add_step({
                "id": f"step-{step_idx + 1}-observation",
                "name": f"工具结果：{action_name}",
                "status": status,
                "output": observation_text,
                "time": time.strftime("%H:%M:%S"),
            })
            emit_log("INFO", f"工具 {action_name} 返回：{observation_text[:200]}", task_id)

            # 把这一轮结果追加到 messages
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"Observation: {observation_text}"})

        else:
            final_answer = "任务步数已达上限，未能完成。请尝试把需求拆小或增加步数限制。"

        # 最终阶段把 result 标记为 completed
        if isinstance(final_answer, dict) and final_answer.get("type") == "report":
            final_answer["status"] = "completed"
            update(status="completed", result=final_answer, current_step="完成")
        else:
            update(status="completed", result=final_answer, current_step="完成")
        emit_log("INFO", "Agent 任务完成", task_id)
    except Exception as exc:
        err = str(exc)
        update(status="failed", error=err, current_step="失败")
        emit_log("ERROR", f"Agent 任务失败：{err}", task_id)


def create_agent_task_id() -> str:
    return uuid.uuid4().hex[:12]
