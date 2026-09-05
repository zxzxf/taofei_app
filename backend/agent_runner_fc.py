"""Function Calling 模式的 Agent Runner。

使用原生 function calling / tool use 替代 ReAct 文本解析，速度更快、准确率更高。

与旧 ReAct 模式的区别：
- 工具调用走 API 的 tools 参数，结构化，无需正则解析
- 系统提示词大幅精简（不用教模型 ReAct 格式）
- 支持并行工具调用
- 工具结果用 role:tool 消息回传，而非拼接 Observation 文本

设计原则：
- 完全兼容旧接口（run_agent_task 签名一致）
- 旧 ReAct 模式保留作为 fallback
- 前端展示层无需改动（仍写 steps / timeline / result 到 task_store）
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

# Function calling 模式的系统提示词 — 只给核心指令和约束，
# 工具定义走 API 的 tools 参数，不在 prompt 里重复。
FC_SYSTEM_PROMPT = """你是一个智能代码助手，可以调用工具来完成任务。

核心规则：
1. 能直接回答的问题直接回答，不要强行调用工具。
2. 需要查找信息、读取文件、执行代码时，调用相应的工具。
3. 可以一次调用多个独立的工具（并行执行）。
4. 除非用户明确要求修改或创建文件，否则任务默认为只读：查询、验证、总结、排查类任务禁止使用 write_file，禁止改动任何文件。
5. 如果用户请求涉及项目文件，优先用 grep_code 全局搜索关键词（比 list_directory + read_file 快很多），找到目标文件后再用 read_file 查看详细内容。
6. 读取文件必须使用 read_file 工具，不得用 run_python_code 替代读文件；run_python_code 仅用于计算、数据处理或运行脚本。
7. 如需创建或修改文件，使用 write_file，修改后直接告诉用户完成情况。
8. 功能开发/代码修改类任务：完成文件修改并验证思路正确后，直接给出最终结论，不要继续探索。
9. 禁止启动后端服务或桌面应用，禁止打开浏览器（webbrowser、os.startfile、start 命令）。验证接口请用 http_request 访问已在运行的服务即可。
10. 用户指令优先级最高。若用户要求与其他规则或工具使用习惯冲突，以用户要求为准；用户明确说"禁止/不要/不得"的操作，一律不执行，不要反向理解。
"""


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


# ---------------------------------------------------------------
# B6：自动技能（source=auto，知识型）按相关度动态注入
# ---------------------------------------------------------------

# 注入上限：最多选 N 个最相关的自动技能，避免 system 过长影响前缀缓存
_AUTO_SKILL_MAX_INJECT = 3
# 最小相关度阈值：关键词重叠数低于此值的技能不注入
_AUTO_SKILL_MIN_SCORE = 1


def _auto_skill_score(skill: dict, user_text: str) -> int:
    """计算自动技能与用户问题的相关度（关键词重叠数，轻量无依赖）。

    打分规则：
    - 把技能名 + 描述 + 内容前 500 字合成文档
    - 分词（中文按字符 2-gram，英文按空格）
    - 与用户问题的 token 集合求交集大小即为分数
    分数越高越相关。纯规则，速度快，不影响前缀缓存稳定性。
    """
    import re

    name = str(skill.get("name", ""))
    desc = str(skill.get("description", ""))
    content = str(skill.get("content", ""))[:500]
    doc = f"{name} {desc} {content}".lower()
    user = (user_text or "").lower()

    # 简单 token 化：英文单词 + 中文字符 2-gram
    def _tokens(text: str) -> set[str]:
        tokens: set[str] = set()
        # 英文单词
        for m in re.findall(r"[a-z][a-z0-9_-]{2,}", text):
            tokens.add(m)
        # 中文 2-gram
        cn = re.findall(r"[\u4e00-\u9fff]", text)
        for i in range(len(cn) - 1):
            tokens.add(cn[i] + cn[i + 1])
        return tokens

    doc_tokens = _tokens(doc)
    user_tokens = _tokens(user)
    if not doc_tokens or not user_tokens:
        return 0
    return len(doc_tokens & user_tokens)


def _build_auto_skill_prompt(user_request: str) -> str | None:
    """B6：从自动知识技能（source=auto）中按相关度选前 N 个注入 system prompt。

    设计原则：
    - 轻量：纯规则打分，不调用 LLM、不用向量，零额外延迟
    - 稳定：按名称排序后输出，相同输入输出顺序固定，保护前缀缓存
    - 克制：最多 3 个，不相关的不注入，避免撑爆 system 前缀
    """
    try:
        from skills_lifecycle import list_my_skills
    except Exception:
        return None

    all_auto = [
        s for s in list_my_skills()
        if str(s.get("source", "")).lower() == "auto"
        and s.get("enabled", True)
    ]
    if not all_auto or not user_request:
        return None

    # 打分 + 过滤
    scored = []
    for s in all_auto:
        score = _auto_skill_score(s, user_request)
        if score >= _AUTO_SKILL_MIN_SCORE:
            scored.append((score, s))

    if not scored:
        return None

    # 按分数降序，同分按名称排序（保证输出稳定 → 前缀缓存稳定）
    scored.sort(key=lambda x: (-x[0], str(x[1].get("name", ""))))
    top = [s for _, s in scored[:_AUTO_SKILL_MAX_INJECT]]

    # 组装片段
    parts = []
    for s in top:
        name = str(s.get("name", "未命名技能"))
        desc = str(s.get("description", "")).strip()
        content = str(s.get("content", "")).strip()
        if not content:
            continue
        head = f"### 技能「{name}」"
        if desc:
            head += f"：{desc}"
        parts.append(f"{head}\n{content}")

    if not parts:
        return None

    return (
        "## 相关知识技能（自动匹配，仅供参考）\n"
        + "\n\n".join(parts)
        + "\n\n当用户问题与上述技能相关时，请优先参考技能中的步骤和方法。"
    )


def _build_user_content(user_request: str, images: list[str]):
    """构造首条用户消息内容：无图返回纯文本，有图返回 OpenAI vision 格式的 content 数组。"""
    if not images:
        return user_request
    blocks: list[dict] = []
    for img in images:
        img = (img or "").strip()
        if not img:
            continue
        m = __import__("re").match(r"^data:([^;]+);base64,(.+)$", img)
        if m:
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{m.group(1)};base64,{m.group(2)}"},
            })
        elif img.startswith("http://") or img.startswith("https://"):
            blocks.append({"type": "image_url", "image_url": {"url": img}})
    if user_request:
        blocks.insert(0, {"type": "text", "text": user_request})
    return blocks if blocks else user_request


def _build_partial_report(steps, user_request, status="running"):
    """构造前端展示用的部分报告（与旧 ReAct 模式格式一致）。"""
    sections = []
    structured_steps = []
    for s in steps:
        structured_steps.append({
            "name": s.get("name", ""),
            "status": s.get("status", "done"),
            "output": s.get("output", ""),
        })
    return {
        "type": "report",
        "title": f"正在处理：{user_request[:30]}…",
        "status": status,
        "duration": "进行中",
        "summary": f"已执行 {len(steps)} 步，最新动作：{steps[-1].get('name', '') if steps else '准备中'}。",
        "sections": sections,
        "steps": structured_steps,
    }


def _extract_tool_calls(response: Any) -> list[dict]:
    """从模型响应中提取 tool_calls。

    兼容多种响应格式：
    - openai SDK: response.message.tool_calls (ChatCompletionMessageToolCall 对象)
    - langchain: response.tool_calls (list of dict)
    - 普通 dict: response["message"]["tool_calls"]
    - 直接是 list
    """
    # list 直接返回
    if isinstance(response, list):
        return response

    # 对象的 .message.tool_calls （openai SDK 风格）
    msg = getattr(response, "message", None)
    if msg is not None:
        tc = getattr(msg, "tool_calls", None)
        if tc:
            # 转成 dict 列表
            result = []
            for c in tc:
                if hasattr(c, "function"):
                    args = c.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    result.append({
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": args if isinstance(args, dict) else {},
                        },
                    })
                elif isinstance(c, dict):
                    result.append(c)
            return result

    # dict 风格
    if isinstance(response, dict):
        msg = response.get("message", response)
        tc = msg.get("tool_calls")
        if tc:
            return tc if isinstance(tc, list) else []

    # langchain AIMessage.tool_calls
    tc = getattr(response, "tool_calls", None)
    if tc and isinstance(tc, list):
        result = []
        for i, c in enumerate(tc):
            if isinstance(c, dict):
                result.append({
                    "id": c.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": c.get("name", ""),
                        "arguments": c.get("args", {}),
                    },
                })
        return result

    return []


def _extract_content(response: Any) -> str:
    """从模型响应中提取文本内容。"""
    if isinstance(response, str):
        return response

    # 对象 .message.content （openai SDK 风格）
    msg = getattr(response, "message", None)
    if msg is not None:
        c = getattr(msg, "content", None)
        if c is not None:
            return c if isinstance(c, str) else ""

    # dict 风格
    if isinstance(response, dict):
        msg = response.get("message", response)
        c = msg.get("content")
        if c:
            return c if isinstance(c, str) else ""

    # langchain AIMessage.content
    c = getattr(response, "content", None)
    if c is not None:
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            # langchain content blocks
            text_parts = []
            for block in c:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)

    return str(response) if response else ""


def run_agent_task_fc(
    task_id: str,
    user_request: str,
    llm_call: Callable[[list[dict], list[dict] | None], Any],
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
) -> None:
    """在后台线程中执行 Function Calling 模式的 Agent。

    与旧 run_agent_task 接口完全一致，前端无需改动。
    llm_call 签名扩展为：llm_call(messages, tools=None) -> response
    若底层 llm_call 不支持 tools 参数，会自动检测并降级到 ReAct 模式。

    history_messages: Session 历史消息（不含 system/user），插在 system 与
        本轮 user 之间。
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

    update(status="running", mode="function_calling")
    task_start_time = time.time()
    emit_log("INFO", f"[FC模式] Agent 任务开始：{user_request[:80]}...", task_id)

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

    # B6：自动知识技能按相关度动态注入（不相关的不注入，保护前缀缓存）
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
    fc_supported = None  # None=未检测, True=支持, False=不支持需降级

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
            emit_log("INFO", f"[FC模式] Agent 第 {step_idx + 1} 次调用模型", task_id)

            # 接近步数上限时提醒
            if step_idx >= MAX_STEPS - 3 and not near_limit_warned:
                messages.append({
                    "role": "user",
                    "content": "注意：你已接近最大步数限制，请根据已执行的工具调用和结果，直接给出最终答案，不要再调用新工具。",
                })
                near_limit_warned = True

            # 调用模型
            response = None
            step_start = time.time()
            try:
                # 尝试带 tools 参数调用
                response = llm_call(messages, tools=openai_tools)
                if fc_supported is None:
                    fc_supported = True
                    emit_log("INFO", "[FC模式] 模型支持 function calling", task_id)
            except TypeError as exc:
                # llm_call 不支持 tools 参数 → 降级到 ReAct
                if fc_supported is None:
                    fc_supported = False
                    emit_log(
                        "WARNING",
                        f"[FC模式] 当前 LLM 不支持 function calling，自动降级为 ReAct 模式：{exc}",
                        task_id,
                    )
                    # 降级：调用旧的 ReAct runner
                    from agent_runner import run_agent_task
                    run_agent_task(
                        task_id=task_id,
                        user_request=user_request,
                        llm_call=lambda msgs: llm_call(msgs),
                        workspace_path=workspace_path,
                        emit_log=emit_log,
                        task_store=task_store,
                        task_lock=task_lock,
                        notify_update=notify_update,
                        images=images,
                        skills=skills,
                        cancel_flag_getter=cancel_flag_getter,
                    )
                    # ReAct 已完成，回写会话（ReAct 结果在 task_store，由 hook 兜底提取）
                    try:
                        if messages_hook:
                            messages_hook(messages)
                    except Exception:
                        pass
                    return
                raise
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
                    response = llm_call(messages, tools=openai_tools)
                else:
                    raise

            # 提取工具调用和文本内容
            tool_calls = _extract_tool_calls(response)
            content = _extract_content(response)

            # 添加思考步骤
            add_step({
                "id": f"step-{step_idx + 1}",
                "name": f"思考第 {step_idx + 1} 步",
                "status": "done",
                "output": content or "（调用工具中…）",
                "thinking": "",
                "time": time.strftime("%H:%M:%S"),
            })

            # 没有工具调用 → 任务完成
            if not tool_calls:
                final_answer = content
                # 把最终回答补成 assistant 消息，保证消息历史自洽（Session 回写需要）
                if content:
                    messages.append({"role": "assistant", "content": content})
                # 添加 timeline
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
            emit_log("INFO", f"[FC模式] 并行调用 {len(tool_calls)} 个工具：{[tc['function']['name'] for tc in tool_calls]}", task_id)

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

            # 先批量添加 running step
            for tc_id, func_name, func_args in parsed_tools:
                add_step({
                    "id": f"step-{step_idx + 1}-action-{func_name}",
                    "name": f"调用工具：{func_name}",
                    "status": "running",
                    "output": json.dumps(func_args, ensure_ascii=False),
                    "time": time.strftime("%H:%M:%S"),
                })
                emit_log("INFO", f"[FC模式] 工具 {func_name}({func_args})", task_id)

            # 预占 timeline
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

            tool_indices = {tc_id: i for i, (tc_id, _, _) in enumerate(parsed_tools)}

            def _run_single_tool(tc_item):
                tc_id, func_name, func_args = tc_item
                try:
                    tool_result_str = execute_tool_fc(
                        func_name, workspace_path,
                        # 兼容 tools kwarg（delegate_tasks 等子代理工具会传子集 schemas）
                        lambda msgs, _tools=None: llm_call(msgs, tools=_tools if _tools is not None else openai_tools),
                        func_args, skills=skills,
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

            # 按原始顺序组装结果
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
                emit_log("INFO", f"[FC模式] 工具 {func_name} 返回：{tool_result_str[:200]}", task_id)

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
            emit_log("WARNING", "[FC模式] Agent 步数耗尽，强制生成总结报告", task_id)
            summary_messages = messages + [
                {
                    "role": "user",
                    "content": "任务步数即将耗尽。请基于以上所有工具调用和结果，直接输出最终总结。",
                },
            ]
            try:
                summary_reply = llm_call(summary_messages, tools=[])
                final_answer = _extract_content(summary_reply)
            except Exception as exc:
                final_answer = f"任务步数已达上限，且生成总结时出错：{exc}。请尝试把需求拆小或增加步数限制。"

        # 完成
        steps = task_store[task_id].get("steps", [])
        cancelled = is_cancelled()
        final_status = "cancelled" if cancelled else "completed"
        computed_report = _build_partial_report(steps, user_request, status=final_status)

        # 思考耗时兜底
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
            # 尝试从 final_answer 中提取 report JSON
            report_data = None
            if isinstance(final_answer, str):
                # 兼容模型直接输出 JSON 报告
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

    except Exception as exc:
        err = str(exc)
        update(status="failed", error=err, current_step="失败")
        emit_log("ERROR", f"[FC模式] Agent 任务失败：{err}", task_id)
        try:
            if messages_hook:
                messages_hook(messages)
        except Exception:
            pass


def create_agent_task_id() -> str:
    return uuid.uuid4().hex[:12]
