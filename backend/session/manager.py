"""SessionManager：会话的内存管理与持久化桥。

- 内存持有活跃会话（LRU 上限 MAX_MEMORY_SESSIONS）
- 空闲超过 IDLE_TTL 秒的会话从内存卸载（SQLite 数据保留，按需重载）
- 每次写盘为增量（只追加新消息），SQLite 是最终持久层
- 线程安全：所有公开方法带锁
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

try:
    import db
except ImportError:  # pragma: no cover
    import backend.db as db

from .session import ChatSession

log = logging.getLogger(__name__)

MAX_MEMORY_SESSIONS = 200   # 内存最多同时持有的会话数
IDLE_TTL = 30 * 60          # 空闲 30 分钟从内存卸载（DB 保留）
REAP_INTERVAL = 5 * 60      # 后台回收线程间隔


class SessionManager:
    """全局会话管理器（应用内单例）。"""

    def __init__(
        self,
        max_memory: int = MAX_MEMORY_SESSIONS,
        idle_ttl: float = IDLE_TTL,
    ) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.RLock()
        self._max_memory = max_memory
        self._idle_ttl = idle_ttl
        self._reaper: threading.Thread | None = None

    # -------------------------------------------------------------
    # 核心操作
    # -------------------------------------------------------------
    def get_or_create(
        self,
        session_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> tuple[ChatSession, bool]:
        """按 id 取会话（内存 → SQLite → 新建）。

        返回 (session, created)。meta 仅在新创建时生效。
        """
        meta = meta or {}
        with self._lock:
            sid = session_id or meta.get("id")
            if sid:
                s = self._get_from_memory_or_db(sid)
                if s is not None:
                    return s, False
            # 新建
            s = ChatSession(
                session_id=sid,
                title=meta.get("title") or "新对话",
                workspace_id=meta.get("workspace_id"),
                model_preset_id=meta.get("model_preset_id"),
                skill_ids=meta.get("skill_ids") or [],
                knowledge_ids=meta.get("knowledge_ids") or [],
                memory_enabled=bool(meta.get("memory_enabled", True)),
            )
            self._sessions[s.id] = s
            # 立即落库元数据（消息为空，等任务完成后增量写）
            db.create_session(s.to_meta())
            self._enforce_lru_locked()
            return s, True

    def get(self, session_id: str) -> ChatSession | None:
        with self._lock:
            return self._get_from_memory_or_db(session_id)

    def _get_from_memory_or_db(self, session_id: str) -> ChatSession | None:
        s = self._sessions.get(session_id)
        if s is not None:
            return s
        row = db.load_session(session_id)
        if row is None:
            return None
        s = ChatSession.from_meta(row, messages=row.get("messages") or [])
        self._sessions[session_id] = s
        self._enforce_lru_locked()
        return s

    def create(self, **meta: Any) -> ChatSession:
        """显式创建空会话（供前端『新建会话』调用）。"""
        with self._lock:
            s = ChatSession(**meta)
            self._sessions[s.id] = s
            db.create_session(s.to_meta())
            self._enforce_lru_locked()
            return s

    def delete(self, session_id: str) -> bool:
        with self._lock:
            self._sessions.pop(session_id, None)
            return db.delete_session(session_id)

    def list(self, limit: int = 100, workspace_id: str | None = None) -> list[dict]:
        """列出会话摘要（DB 为准，不加载内存消息）。"""
        return db.list_sessions(limit=limit, workspace_id=workspace_id)

    def save(self, session: ChatSession) -> None:
        """增量持久化会话（元数据 + 未写盘消息）。"""
        with self._lock:
            # 元数据（updated_at 等）
            db.update_session_meta(
                session.id,
                title=session.title,
                workspace_id=session.workspace_id,
                model_preset_id=session.model_preset_id,
                skill_ids=session.skill_ids,
                knowledge_ids=session.knowledge_ids,
                memory_enabled=session.memory_enabled,
                updated_at=session.updated_at,
            )
            # 增量消息
            pending = session.pending_messages()
            if pending:
                db.append_session_messages(session.id, pending)
                session.mark_persisted()

    def mark_busy(self, session: ChatSession, delta: int = 1) -> None:
        with self._lock:
            session.busy = max(0, session.busy + delta)

    # -------------------------------------------------------------
    # 内存回收
    # -------------------------------------------------------------
    def _enforce_lru_locked(self) -> None:
        """内存会话数超限时，卸载最久未活跃的非繁忙会话。"""
        if len(self._sessions) <= self._max_memory:
            return
        idle = [
            (s.updated_at, sid)
            for sid, s in self._sessions.items()
            if s.busy <= 0
        ]
        idle.sort()
        overflow = len(self._sessions) - self._max_memory
        for _, sid in idle[: overflow + 8]:  # 多卸几个留余量
            self._sessions.pop(sid, None)

    def _reap_idle(self) -> None:
        """卸载空闲超时会话（数据已在 SQLite，仅释放内存）。"""
        cutoff = time.time() - self._idle_ttl
        with self._lock:
            stale = [
                sid for sid, s in self._sessions.items()
                if s.busy <= 0 and s.updated_at < cutoff
            ]
            for sid in stale:
                self._sessions.pop(sid, None)

    def start_reaper(self) -> None:
        """启动后台回收线程（幂等）。"""
        with self._lock:
            if self._reaper is not None and self._reaper.is_alive():
                return

            def _loop() -> None:
                while True:
                    time.sleep(REAP_INTERVAL)
                    try:
                        self._reap_idle()
                    except Exception:
                        log.exception("会话回收线程异常")

            self._reaper = threading.Thread(target=_loop, name="session-reaper", daemon=True)
            self._reaper.start()

    # -------------------------------------------------------------
    # 工具
    # -------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "memory_sessions": len(self._sessions),
                "max_memory": self._max_memory,
                "idle_ttl": self._idle_ttl,
                "reaper_alive": bool(self._reaper and self._reaper.is_alive()),
            }


_manager: SessionManager | None = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """应用内单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SessionManager()
                _manager.start_reaper()
    return _manager
