"""ChatSession：单个对话会话的内存表示。

持有：
- 元数据：id / title / workspace_id / model_preset_id / skill_ids /
  knowledge_ids / memory_enabled / created_at / updated_at
- messages：OpenAI 兼容原始消息列表（不含 system，system 由每次请求动态组装）
  - {"role": "user", "content": str | list[blocks]}
  - {"role": "assistant", "content": str, "tool_calls": [...]}
  - {"role": "tool", "tool_call_id": "...", "content": str}

持久化由 SessionManager 负责（增量写 SQLite）。
"""
from __future__ import annotations

import time
import uuid
from typing import Any


class ChatSession:
    """一个跨请求持久的对话会话。非线程安全——由 SessionManager 加锁保护。"""

    def __init__(
        self,
        session_id: str | None = None,
        *,
        title: str = "新对话",
        workspace_id: str | None = None,
        model_preset_id: str | None = None,
        skill_ids: list[str] | None = None,
        knowledge_ids: list[str] | None = None,
        memory_enabled: bool = True,
        messages: list[dict] | None = None,
    ) -> None:
        now = time.time()
        self.id = session_id or uuid.uuid4().hex[:12]
        self.title = title or "新对话"
        self.workspace_id = workspace_id
        self.model_preset_id = model_preset_id
        self.skill_ids = list(skill_ids or [])
        self.knowledge_ids = list(knowledge_ids or [])
        self.memory_enabled = memory_enabled
        self.created_at = now
        self.updated_at = now
        self.messages: list[dict] = [dict(m) for m in (messages or [])]
        # 已持久化到 SQLite 的消息条数（增量写盘）
        self._persisted_count = 0
        # 正在执行 Agent 任务的次数（>0 时禁止从内存卸载）
        self.busy = 0
        # 上下文压缩进行中（防重入）
        self._compressing = False

    # -------------------------------------------------------------
    # 消息操作
    # -------------------------------------------------------------
    def append_messages(self, messages: list[dict]) -> None:
        """追加一批消息（浅拷贝），并更新时间戳。"""
        if not messages:
            return
        for m in messages:
            self.messages.append(dict(m))
        self.touch()

    def touch(self) -> None:
        self.updated_at = time.time()

    def set_title_if_empty(self, fallback: str | None) -> None:
        if (not self.title or self.title == "新对话") and fallback:
            self.title = fallback.strip()[:40] or "新对话"

    def pending_messages(self) -> list[dict]:
        """返回尚未持久化的消息。"""
        return self.messages[self._persisted_count:]

    def mark_persisted(self) -> None:
        self._persisted_count = len(self.messages)

    # -------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------
    def to_meta(self) -> dict[str, Any]:
        """元数据（不含消息），用于 DB 写入与 API 响应。"""
        return {
            "id": self.id,
            "title": self.title,
            "workspace_id": self.workspace_id,
            "model_preset_id": self.model_preset_id,
            "skill_ids": list(self.skill_ids),
            "knowledge_ids": list(self.knowledge_ids),
            "memory_enabled": self.memory_enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self, with_messages: bool = True) -> dict[str, Any]:
        data = self.to_meta()
        if with_messages:
            data["messages"] = [dict(m) for m in self.messages]
        return data

    @classmethod
    def from_meta(cls, meta: dict[str, Any], messages: list[dict] | None = None) -> "ChatSession":
        """从 DB 加载的 meta 重建（时间戳用 DB 值，不重置）。"""
        s = cls(
            session_id=meta.get("id"),
            title=meta.get("title") or "新对话",
            workspace_id=meta.get("workspace_id"),
            model_preset_id=meta.get("model_preset_id"),
            skill_ids=meta.get("skill_ids") or [],
            knowledge_ids=meta.get("knowledge_ids") or [],
            memory_enabled=bool(meta.get("memory_enabled", True)),
            messages=messages,
        )
        s.created_at = float(meta.get("created_at") or s.created_at)
        s.updated_at = float(meta.get("updated_at") or s.updated_at)
        s._persisted_count = len(s.messages)
        return s
