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
from datetime import datetime, timezone
from typing import Any, Callable

from agent_tools import TOOLS, build_skill_tools, execute_tool

MAX_STEPS = 25


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
6. 用户指令优先级最高。若用户要求与其他规则或工具使用习惯冲突，以用户要求为准；用户明确说"禁止/不要/不得"的操作，一律不执行，不要反向理解。
7. 除非用户明确要求修改或创建文件，否则任务默认为只读：查询、验证、总结、排查类请求禁止使用 write_file，禁止改动任何文件。
8. 如果用户请求涉及项目文件，优先使用 grep_code 全局搜索关键词（比 list_directory + read_file 快很多），找到目标文件后再用 read_file 查看详细内容。不要反复 list_directory 逐层找文件。
9. 读取文件必须使用 read_file 工具，不得用 run_python_code 替代读文件；run_python_code 仅用于计算、数据处理或运行脚本。
10. 如需创建或修改文件，使用 write_file，修改后必须输出 Final Answer 报告完成情况。
11. 功能开发/代码修改类任务：完成文件修改并验证思路正确后，立即输出 Final Answer，不要继续探索。
12. 禁止启动后端服务或桌面应用（python backend/main.py、TaofeiAPI.exe、TaofeiAI.exe 等），禁止打开浏览器（webbrowser、os.startfile、start 命令）。验证接口请用 http_request 访问已在运行的服务即可。
"""


def _format_tools(tools: list[dict] | None = None) -> str:
    lines = []
    for t in tools or TOOLS:
        lines.append(f"- {t['name']}: {t['description']}")
        lines.append(f"  参数: {json.dumps(t['parameters'], ensure_ascii=False)}")
    return "\n".join(lines)


def _build_skill_prompts(skills: list[dict]) -> str:
    """把 Claude 类型技能的 instructions 拼成 system prompt 片段。"""
    parts = []
    for sk in skills or []:
        if sk.get("type") != "claude" or not sk.get("enabled", True):
            continue
        name = sk.get("name") or sk.get("id") or "未命名技能"
        desc = str(sk.get("description") or "").strip()
        instr = str(sk.get("instructions") or "").strip()
        head = f"技能「{name}」：{desc}" if desc else f"技能「{name}」"
        if instr:
            parts.append(f"{head}\n使用方法（instructions）：\n{instr}")
        else:
            parts.append(head)
    return "\n\n".join(parts)


def _sanitize_model_output(text: str) -> tuple[str, str]:
    """去除模型可能输出的 XML 包装标签，同时提取思考内容。

    返回 (clean_text, thinking_text)。思考类标签（<think>/<thinking>）的内容
    会被提取到 thinking_text 中，不再泄露到用户界面正文。
    """
    thinking_parts: list[str] = []

    def _save_thinking(m: re.Match) -> str:
        content = m.group(1).strip()
        if content:
            thinking_parts.append(content)
        return ""

    # 1) 提取整个思考块内容，然后移除标签
    text = re.sub(r"<thinking[^>]*>(.*?)</thinking\s*>", _save_thinking, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</thinking\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<think[>\s](.*?)</think\s*>", _save_thinking, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</think\s*>", "", text, flags=re.IGNORECASE)
    # 2) 移除 tool_call/tool_response 包装标签（保留内容）
    text = re.sub(r"</?tool_call>\s*", "", text)
    text = re.sub(r"</?tool_response>\s*", "", text)
    # 3) 去掉可能残留的 "♪" 等豆包思考链标记字符
    text = re.sub(r"^[♪\s]+", "", text)
    return text.strip(), "\n\n".join(thinking_parts)


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
    text, _ = _sanitize_model_output(text)

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
    text, _ = _sanitize_model_output(text)
    return "Final Answer:" in text


def _extract_final_answer(text: str) -> str:
    text, _ = _sanitize_model_output(text)
    match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _extract_thought(text: str) -> str:
    """从模型输出中提取 Thought 内容（去掉前缀和 Action 之后的部分），用于前端展示。"""
    text, _ = _sanitize_model_output(text)
    # 匹配 Thought: ... 到 Action:/Final Answer: 之前
    match = re.search(r"Thought:\s*(.*?)(?=\n\s*(?:Action:|Final Answer:|Action Input:))", text, re.DOTALL | re.IGNORECASE)
    if match:
        thought = match.group(1).strip()
        if thought:
            return thought
    # 如果没有标准格式，返回原文前 200 字
    return text.strip()[:300]


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
        # 过滤纯内部状态步骤：格式重试（思考第 N 步保留，让用户能看到思考过程）
        if name == "格式重试":
            continue
        items.append(f"{icon} {name}")
    duration = "进行中"
    if steps:
        try:
            from datetime import datetime, timedelta

            first = steps[0].get("time", "")
            last = steps[-1].get("time", "")
            if first and last:
                fmt = "%H:%M:%S"
                t1 = datetime.strptime(first, fmt)
                t2 = datetime.strptime(last, fmt)
                delta: timedelta = t2 - t1
                # 如果跨午夜，把差值修正为正数
                secs = delta.total_seconds()
                if secs < 0:
                    secs += 24 * 60 * 60
                duration = f"{int(secs // 60)}m{int(secs % 60)}s"
        except Exception:
            pass
    sections = []
    # 不再生成"执行步骤"章节：执行过程已通过 timeline（思考过程）展示，避免重复
    return {
        "type": "report",
        "title": f"正在处理：{user_request[:30]}…",
        "status": status,
        "duration": duration,
        "summary": f"已执行 {len(steps)} 步，最新动作：{steps[-1].get('name', '') if steps else '准备中'}。",
        "sections": sections,
        "steps": structured_steps,
    }


def _is_report_json(text: str) -> bool:
    return text.strip().startswith("{") and '"type"' in text and '"report"' in text


def _build_user_content(user_request: str, images: list[str]):
    """构造首条用户消息内容：无图返回纯文本，有图返回 Anthropic 多模态 blocks。"""
    if not images:
        return user_request
    blocks: list[dict] = []
    for img in images:
        img = (img or "").strip()
        if not img:
            continue
        m = re.match(r"^data:([^;]+);base64,(.+)$", img)
        if m:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)},
            })
        elif img.startswith("http://") or img.startswith("https://"):
            blocks.append({"type": "image", "source": {"type": "url", "url": img}})
    if user_request:
        blocks.append({"type": "text", "text": user_request})
    return blocks if blocks else user_request


def run_agent_task(
    task_id: str,
    user_request: str,
    llm_call: Callable[[list[dict]], str],
    workspace_path: str | None,
    emit_log: Callable[..., Any],
    task_store: dict[str, dict],
    task_lock: threading.Lock,
    notify_update: Callable[[], None] | None = None,
    images: list[str] | None = None,
    skills: list[dict] | None = None,
    cancel_flag_getter: Callable[[], bool] | None = None,
) -> None:
    """在后台线程中执行 ReAct Agent。

    images: 首条用户消息附带的多模态图片（data URL 或 URL 列表）。
    skills: 会话绑定的技能列表（HTTP 技能注册为 call_skill_<id> 工具，
            Claude 技能 instructions 注入 system prompt）。
    cancel_flag_getter: 可选，返回 True 时任务应尽快停止。
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
            # 每完成一步都刷新部分报告，前端轮询/SSE 时能看到逐步成形
            task_store[task_id]["result"] = _build_partial_report(
                task_store[task_id]["steps"], user_request, status="running"
            )
        if notify_update:
            notify_update()

    update(status="running")
    task_start_time = time.time()
    emit_log("INFO", f"Agent 任务开始：{user_request[:80]}...", task_id)

    # 会话绑定技能：HTTP 技能注册为动态工具，Claude 技能 instructions 注入 system prompt
    skills = skills or []
    skill_tools = build_skill_tools(skills)
    all_tools = TOOLS + skill_tools
    system_content = REACT_SYSTEM_PROMPT.format(tools_desc=_format_tools(all_tools))
    skill_prompt = _build_skill_prompts(skills)
    if skill_prompt:
        system_content += "\n\n## 已启用技能（请根据用户需求判断是否需要使用）\n" + skill_prompt

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": _build_user_content(user_request, images or [])},
    ]

    final_answer = ""
    near_limit_warned = False
    try:
        for step_idx in range(MAX_STEPS):
            # 检查取消标志
            if is_cancelled():
                emit_log("INFO", "任务已被用户取消", task_id)
                break
            # 更新当前步骤；若已有步骤则刷新部分报告摘要，让前端能看到"正在思考第 N 步"
            with task_lock:
                task_store[task_id]["current_step"] = f"思考第 {step_idx + 1} 步"
                _steps = task_store[task_id].get("steps", [])
                if _steps:
                    _rpt = _build_partial_report(_steps, user_request, status="running")
                    _rpt["summary"] = f"⏳ 正在思考第 {step_idx + 1} 步…"
                    task_store[task_id]["result"] = _rpt
            if notify_update:
                notify_update()
            emit_log("INFO", f"Agent 第 {step_idx + 1} 次调用模型", task_id)

            # 接近步数上限时提醒模型直接总结，避免无意义地继续调用工具
            if step_idx >= MAX_STEPS - 3 and not near_limit_warned:
                messages.append({
                    "role": "user",
                    "content": "注意：你已接近最大步数限制，请根据已执行的工具调用和观察结果，直接输出 Final Answer 总结当前进展，不要再调用新工具。",
                })
                near_limit_warned = True

            reply = None
            step_start = time.time()
            try:
                reply = llm_call(messages)
            except Exception as exc:
                # 当前模型不支持图片时自动降级：去掉首条消息中的图片后重试一次
                first_user = messages[1] if len(messages) > 1 else None
                has_image_blocks = (
                    isinstance(first_user, dict)
                    and isinstance(first_user.get("content"), list)
                    and any(isinstance(b, dict) and b.get("type") == "image" for b in first_user["content"])
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
                    reply = llm_call(messages)
                else:
                    raise

            # 从原始回复中提取思考内容（在 sanitize 之前）
            raw_thinking = ""
            if reply:
                _, raw_thinking = _sanitize_model_output(reply)

            # 累积思考时长
            if raw_thinking:
                with task_lock:
                    if "thinking_start" not in task_store[task_id]:
                        task_store[task_id]["thinking_start"] = step_start
                    task_store[task_id]["thinking_duration"] = max(
                        task_store[task_id].get("thinking_duration", 0),
                        int(time.time() - task_store[task_id].get("thinking_start", step_start)),
                    )
                if notify_update:
                    notify_update()

            add_step({
                "id": f"step-{step_idx + 1}",
                "name": f"思考第 {step_idx + 1} 步",
                "status": "done",
                "output": _extract_thought(reply),
                "thinking": raw_thinking,
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

            tool_result = execute_tool(action_name, workspace_path, llm_call, args, skills=skills)
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

            # 构建 timeline：将思考和命令执行合并为统一时间线索引
            with task_lock:
                timeline = task_store[task_id].get("timeline", [])
                # 添加思考项：优先用 <thinking> 标签内容，否则用 Thought 前缀内容
                thinking_content = raw_thinking or _extract_thought(reply or "")
                if thinking_content:
                    timeline.append({
                        "type": "thinking",
                        "content": thinking_content,
                        "time": time.strftime("%H:%M:%S"),
                        "elapsed": int(time.time() - task_start_time),
                    })
                # 添加命令执行项
                timeline.append({
                    "type": "command",
                    "name": action_name,
                    "args": args,
                    "result": observation_text,
                    "status": status,
                    "time": time.strftime("%H:%M:%S"),
                    "elapsed": int(time.time() - task_start_time),
                })
                task_store[task_id]["timeline"] = timeline
            if notify_update:
                notify_update()

            # 把这一轮结果追加到 messages
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"Observation: {observation_text}"})

        else:
            # 步数耗尽但模型未主动输出 Final Answer：强制让模型基于已有对话生成总结报告
            emit_log("WARNING", "Agent 步数耗尽，强制生成总结报告", task_id)
            summary_messages = messages + [
                {
                    "role": "user",
                    "content": "任务步数即将耗尽。请基于以上所有 Thought、Action 和 Observation，直接输出 Final Answer 总结你已完成的工作、当前状态和后续建议。",
                }
            ]
            try:
                summary_reply = llm_call(summary_messages)
                if _has_final_answer(summary_reply):
                    final_answer = _extract_final_answer(summary_reply)
                else:
                    final_answer = summary_reply
            except Exception as exc:
                final_answer = f"任务步数已达上限，且生成总结时出错：{exc}。请尝试把需求拆小或增加步数限制。"

        # 最终阶段把 result 标记为 completed，并统一包装为 report dict，
        # 防止前端残留 running 状态的部分报告导致 badge 一直显示“进行中”。
        steps = task_store[task_id].get("steps", [])
        cancelled = is_cancelled()
        final_status = "cancelled" if cancelled else "completed"
        computed_report = _build_partial_report(steps, user_request, status=final_status)
        # 思考耗时兜底：模型未返回 thinking 内容时，用任务总执行时长作为思考耗时
        if not task_store[task_id].get("thinking_duration"):
            with task_lock:
                task_store[task_id]["thinking_duration"] = max(1, int(time.time() - task_start_time))
        if cancelled:
            final_report = computed_report
            final_report["title"] = f"已取消：{user_request[:30]}…"
            final_report["summary"] = f"任务已被用户取消，已执行 {len(steps)} 步。"
            update(status="cancelled", result=final_report, current_step="已取消")
            emit_log("INFO", "Agent 任务已取消", task_id)
        elif isinstance(final_answer, dict) and final_answer.get("type") == "report":
            final_answer["status"] = "completed"
            final_answer["steps"] = steps
            # 模型自己生成的 report 可能没有 duration 或带占位符，统一用计算值覆盖
            if not final_answer.get("duration") or final_answer.get("duration") == "进行中":
                final_answer["duration"] = computed_report.get("duration", "进行中")
            update(status="completed", result=final_answer, current_step="完成")
            emit_log("INFO", "Agent 任务完成", task_id)
        else:
            final_report = computed_report
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
