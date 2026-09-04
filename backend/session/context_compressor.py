"""会话上下文压缩器（P2 任务 7）。

Session 消息累计超过阈值时，把早期完整轮压缩成一条摘要消息，
保留最近 N 轮完整对话，避免长对话无限膨胀拖慢推理 / 超出窗口。

压缩策略（任务 7.2）：
- 触发：消息总字符 > THRESHOLD_CHARS（默认 40_000，≈1-2 万 token 中文）
        或总轮数 > MAX_ROUNDS（默认 40，防纯短消息长会话）
- 保留：最近 KEEP_ROUNDS 个完整轮（user → assistant 结束，中间含工具调用）
- 摘要：早期轮文本化 → 辅助 LLM 提炼关键事实 / 决定 / 标识符 → 作为首条消息
- 安全截断：只在 user 消息边界切（assistant(tool_calls) 与其 tool 结果永不分离）
- 摘要消息 role=user 并带固定前缀，runner 注入时不会被误当本轮输入；
  再次压缩时旧摘要会自动并入新一轮摘要
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# 压缩触发阈值（字符）。中文约 1-2 token/字，40k chars ≈ 安全低于 64k 窗口一半
THRESHOLD_CHARS = int(os.getenv("TAOFEI_COMPRESS_THRESHOLD_CHARS", "40000"))
# 保留最近完整轮数
KEEP_ROUNDS = int(os.getenv("TAOFEI_COMPRESS_KEEP_ROUNDS", "6"))
# 总轮数超过该值也压缩（短消息长会话场景）
MAX_ROUNDS = int(os.getenv("TAOFEI_COMPRESS_MAX_ROUNDS", "40"))
# 摘要消息内容上限
SUMMARY_MAX_CHARS = int(os.getenv("TAOFEI_COMPRESS_SUMMARY_CHARS", "3000"))
# 送进摘要 LLM 的早期文本总量上限
_EARLY_INPUT_MAX_CHARS = 20000
# 单条消息进摘要的最大长度
_MSG_MAX_CHARS = 1200

SUMMARY_PREFIX = "[早期对话摘要] "


# -------------------------------------------------------------
# 工具
# -------------------------------------------------------------
def _msg_text(m: dict) -> str:
    """消息 → 纯文本（兼容 str 与多模态 blocks）。"""
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return str(c or "")


def _msg_chars(m: dict) -> int:
    return len(_msg_text(m))


def estimate_chars(messages: list[dict]) -> int:
    return sum(_msg_chars(m) for m in messages)


def is_summary_message(m: dict) -> bool:
    return m.get("role") == "user" and str(m.get("content", "")).startswith(SUMMARY_PREFIX)


def round_starts(messages: list[dict]) -> list[int]:
    """返回每个完整轮的起点 idx（user 消息位置；首条若为旧摘要则并入 early）。"""
    starts = []
    for i, m in enumerate(messages):
        if m.get("role") == "user" and not is_summary_message(m):
            starts.append(i)
    return starts


def should_compress(messages: list[dict]) -> bool:
    """判断是否需要压缩。"""
    if len(messages) < 8:
        return False
    starts = round_starts(messages)
    if len(starts) <= KEEP_ROUNDS + 2:
        # 轮数不多但消息可能巨长（工具结果）——仍按字符阈值判断
        return estimate_chars(messages) > THRESHOLD_CHARS
    return estimate_chars(messages) > THRESHOLD_CHARS or len(starts) > MAX_ROUNDS


# -------------------------------------------------------------
# 摘要
# -------------------------------------------------------------
def _flatten_early(messages: list[dict]) -> str:
    """把早期消息文本化为 LLM 可读的对话记录（截断控量）。"""
    parts = []
    total = 0
    for m in messages:
        role = m.get("role")
        text = _msg_text(m).strip()
        if not text:
            continue
        if len(text) > _MSG_MAX_CHARS:
            text = text[:_MSG_MAX_CHARS] + "…(截断)"
        if role == "user":
            label = "用户"
        elif role == "assistant":
            tcs = m.get("tool_calls")
            if tcs:
                names = ", ".join(
                    (tc.get("function") or {}).get("name", "") if isinstance(tc, dict) else ""
                    for tc in tcs
                )
                label = f"助手(调用了工具: {names or '?'})"
            else:
                label = "助手"
        elif role == "tool":
            # 工具结果只保留前 300 字符，避免撑爆摘要输入
            text = text[:300] + ("…(截断)" if len(text) > 300 else "")
            label = "工具结果"
        else:
            continue
        parts.append(f"{label}: {text}")
        total += len(text) + len(label) + 3
        if total > _EARLY_INPUT_MAX_CHARS:
            parts.append("…(更早内容略)")
            break
    return "\n\n".join(parts)


_SUMMARY_PROMPT = (
    "下面是一段 AI 助手与用户的早期对话记录（可能包含工具调用及结果）。"
    "请提炼一份**简洁的中文背景摘要**，供后续对话继续参考。要求：\n"
    "1. 保留：用户的核心目标/偏好/要求、已确认的事实与决定、给出的专有名词/编号/标识符、"
    "尚未完成的任务、值得记住的约束。\n"
    "2. 丢弃：寒暄、过程性细节、工具返回的临时数据。\n"
    "3. 输出纯文本，不要 JSON 包裹，不超过 500 字。\n\n"
    "对话记录如下：\n\n{history}"
)


def summarize_early(llm_call: Callable, early_messages: list[dict], emit_log: Callable | None = None) -> str:
    """调用辅助 LLM 生成早期对话摘要。失败返回空串（调用方跳过压缩）。"""
    history_text = _flatten_early(early_messages)
    if not history_text:
        return ""
    try:
        result = llm_call([{"role": "user", "content": _SUMMARY_PROMPT.format(history=history_text[:30000])}])
        text = result.strip() if isinstance(result, str) else str(result or "").strip()
        # 去掉可能的 markdown 包裹
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith(("json", "text", "markdown")):
                text = text.split("\n", 1)[1] if "\n" in text else ""
        return text[:SUMMARY_MAX_CHARS]
    except Exception as exc:
        if emit_log:
            emit_log("WARNING", f"上下文摘要生成失败：{exc}", None)
        return ""


# -------------------------------------------------------------
# 主入口
# -------------------------------------------------------------
def compress_messages(messages: list[dict], llm_call: Callable, emit_log: Callable | None = None) -> list[dict] | None:
    """对消息列表执行压缩，返回新列表；无需压缩或失败返回 None。"""
    if not should_compress(messages):
        return None
    starts = round_starts(messages)
    if not starts:
        return None
    # 保留最近 KEEP_ROUNDS 轮：切在倒数第 KEEP_ROUNDS 个 user 起点
    keep_from = starts[-KEEP_ROUNDS] if len(starts) >= KEEP_ROUNDS else starts[0]
    early = messages[:keep_from]
    kept = messages[keep_from:]
    if not early:
        return None

    summary = summarize_early(llm_call, early, emit_log=emit_log)
    if not summary:
        return None
    if emit_log:
        emit_log("INFO", f"上下文压缩：{len(early)} 条早期消息 → 1 条摘要（保留 {len(kept)} 条）", None)
    summary_msg: dict = {"role": "user", "content": SUMMARY_PREFIX + summary}
    return [summary_msg] + kept


def maybe_compress_session(session: Any, llm_call: Callable, emit_log: Callable | None = None) -> bool:
    """对 ChatSession 执行压缩（含落库）。返回是否压缩成功。

    - 使用 session 上的压缩锁防并发重入
    - 压缩结果整体替换内存消息 + 重建 DB 消息行
    """
    if getattr(session, "_compressing", False):
        return False
    try:
        session._compressing = True
        messages = list(session.messages)
        new_messages = compress_messages(messages, llm_call, emit_log=emit_log)
        if not new_messages:
            return False
        # 原子替换内存引用 + 落库（db 层整表替换）
        import db
        ok = db.replace_session_messages(session.id, new_messages)
        if ok:
            session.messages = new_messages
            session._persisted_count = len(new_messages)
            session.touch()
            if emit_log:
                emit_log("INFO", f"会话 {session.id} 已压缩：{len(messages)} → {len(new_messages)} 条", None)
            return True
        return False
    except Exception as exc:
        if emit_log:
            emit_log("WARNING", f"会话压缩失败：{exc}", None)
        return False
    finally:
        session._compressing = False
