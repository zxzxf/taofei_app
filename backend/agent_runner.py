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


REACT_SYSTEM_PROMPT = """你是一个能调用工具完成复杂任务的 Agent。请严格按以下 ReAct 格式思考并行动。

可用工具：
{tools_desc}

输出格式要求（必须严格遵循）：
Thought: 你对当前任务的分析和下一步计划
Action: 工具名称（必须是上面列出的工具之一）
Action Input: {{"参数名": "参数值"}}

注意：Observation 是工具执行后的结果，由系统自动填入，你不需要写 Observation。

正确示例：
Thought: 我需要先查看当前目录结构
Action: list_directory
Action Input: {{"path": ""}}

错误示例（不要这样做）：
Thought: 我需要先查看当前目录结构
Action: list_directory
Action Input: ```json\n{{"path": ""}}\n```

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
2. Action Input 必须是合法 JSON，不要加 markdown 代码块，不要在 JSON 前后写解释文字。
3. 不要写 Observation，Observation 由系统在工具执行后自动填入。
4. 禁止使用 <tool_call>、<think>、<tool_response> 等 XML 标签，只输出纯文本 ReAct 格式。
5. 不要输出 ``` 代码块包裹 JSON。
6. 如果用户请求涉及项目文件，优先使用 list_directory 和 read_file 查看文件。
7. 如需创建或修改文件，使用 write_file。
8. 如需计算或运行脚本，使用 run_python_code。
9. 如果需要模型帮你总结、改写、分析，使用 ask_llm。
"""


def _format_tools() -> str:
    lines = []
    for t in TOOLS:
        lines.append(f"- {t['name']}: {t['description']}")
        lines.append(f"  参数: {json.dumps(t['parameters'], ensure_ascii=False)}")
    return "\n".join(lines)


def _sanitize_model_output(text: str) -> str:
    """去除 Qwen 等模型可能输出的 <tool_call>/<think> 等 XML 包装标签。"""
    # 移除成对的 XML 标签但保留标签内文本
    text = re.sub(r"</?tool_call>\s*", "", text)
    text = re.sub(r"</?tool_response>\s*", "", text)
    text = re.sub(r"</?think>\s*", "", text)
    return text.strip()


def _extract_json_objects(text: str) -> list[str]:
    """从文本中提取所有顶层 JSON 对象字符串（支持嵌套）。"""
    candidates: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            in_string = False
            escape = False
            for j in range(i, len(text)):
                ch = text[j]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"' and not in_string:
                    in_string = True
                elif ch == '"' and in_string:
                    in_string = False
                elif not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidates.append(text[i : j + 1])
                            i = j
                            break
        i += 1
    return candidates


def _parse_action(text: str) -> tuple[str, dict] | None:
    """从模型输出中解析 Action 和 Action Input。兼容 markdown 代码块、XML 包装、解释文字、tool_call JSON 等。"""
    text = _sanitize_model_output(text)

    action_match = re.search(r"Action:\s*(\S+)", text)
    if action_match:
        action_name = action_match.group(1).strip()

        args: dict = {}

        # 1) 优先尝试 ```json {...} ``` 代码块
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block_match:
            try:
                args = json.loads(code_block_match.group(1))
                return action_name, args
            except Exception:
                pass

        # 2) 标准 Action Input: {...}（紧跟在 Action Input 后的第一个 JSON）
        section_match = re.search(r"Action Input:\s*(.*?)(?:Observation:|$)", text, re.DOTALL)
        if section_match:
            section = section_match.group(1)
            for candidate in _extract_json_objects(section):
                try:
                    args = json.loads(candidate)
                    return action_name, args
                except Exception:
                    continue

        # 3) 兜底：全文中任意位置找第一个合法 JSON 对象
        for candidate in _extract_json_objects(text):
            try:
                args = json.loads(candidate)
                return action_name, args
            except Exception:
                continue

        return action_name, args

    # 4) 兼容 Qwen 等模型直接输出 tool_call JSON（没有 Thought/Action 标签）
    for candidate in _extract_json_objects(text):
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        # 格式 A: {"name": "tool", "arguments": {...}}
        if "name" in data and "arguments" in data:
            name = str(data["name"]).strip()
            args = data["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if isinstance(args, dict):
                return name, dict(args)

        # 格式 B: {"function": {"name": "tool", "arguments": {...}}}
        if "function" in data and isinstance(data["function"], dict):
            fn = data["function"]
            name = str(fn.get("name", "")).strip()
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name and isinstance(args, dict):
                return name, dict(args)

        # 格式 C: {"tool_name": {...}}
        for tool in TOOLS:
            tname = tool["name"]
            if tname in data and isinstance(data[tname], dict):
                return tname, dict(data[tname])

    return None


def _has_final_answer(text: str) -> bool:
    return "Final Answer:" in _sanitize_model_output(text)


def _extract_final_answer(text: str) -> str:
    text = _sanitize_model_output(text)
    match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _build_partial_report(steps: list[dict], user_request: str, status: str = "running") -> dict:
    """根据当前步骤生成部分报告，供前端伪流式展示。"""
    items = []
    structured_steps = []
    for st in steps:
        icon = "⏳" if st.get("status") == "running" else "✅" if st.get("status") == "done" else "❌"
        name = st.get("name", "")
        structured_steps.append({
            "id": st.get("id", ""),
            "name": name,
            "status": st.get("status", ""),
            "output": st.get("output", ""),
            "time": st.get("time", ""),
            "icon": icon,
        })
        # 简洁列表仍保留，用于兼容旧版/无 steps 字段的渲染
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
        "steps": structured_steps,
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
                emit_log("WARNING", f"模型输出未能解析为 ReAct 格式，原始输出：\n{reply}", task_id)
                # 让模型重试一次
                retry_msg = (
                    "你刚才的输出格式不正确。请严格按以下 ReAct 格式输出：\n\n"
                    "正确示例：\n"
                    "Thought: 我需要先查看当前目录结构\n"
                    "Action: list_directory\n"
                    'Action Input: {"path": ""}\n\n'
                    "如果已完成任务，请输出：\n"
                    "Final Answer: 给用户的最终答案\n\n"
                    "注意：\n"
                    "- 不要加 markdown 代码块\n"
                    "- 不要写 Observation\n"
                    "- 禁止使用 <tool_call>、<think>、<tool_response> 等 XML 标签\n"
                    "- Action Input 必须是合法 JSON\n"
                    "- 每次只能输出一轮 Thought + Action + Action Input"
                )
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": retry_msg})
                add_step({
                    "id": f"step-{step_idx + 1}-retry",
                    "name": "格式重试",
                    "status": "done",
                    "output": f"模型未按 ReAct 格式输出，已提示重试。原始输出：\n{reply[:500]}",
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

        # 最终阶段把 result 标记为 completed，并统一包装为 report dict，
        # 防止前端残留 running 状态的部分报告导致 badge 一直显示“进行中”。
        steps = task_store[task_id].get("steps", [])
        if isinstance(final_answer, dict) and final_answer.get("type") == "report":
            final_answer["status"] = "completed"
            final_answer["steps"] = steps
            update(status="completed", result=final_answer, current_step="完成")
        else:
            final_report = _build_partial_report(steps, user_request, status="completed")
            final_report["title"] = f"已完成：{user_request[:30]}…"
            final_report["summary"] = str(final_answer) if final_answer else "Agent 已完成任务。"
            update(status="completed", result=final_report, current_step="完成")
        emit_log("INFO", "Agent 任务完成", task_id)
    except Exception as exc:
        err = str(exc)
        update(status="failed", error=err, current_step="失败")
        emit_log("ERROR", f"Agent 任务失败：{err}", task_id)


def create_agent_task_id() -> str:
    return uuid.uuid4().hex[:12]
