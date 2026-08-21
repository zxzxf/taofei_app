"""WebSocket 连接与订阅管理器。

每个客户端连接对应一个 WebSocket 对象，客户端可以通过 subscribe/unsubscribe
消息订阅多个 task_id 的状态更新和日志流。任务状态变化 / 新日志产生时主动推送。
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Callable

from fastapi import WebSocket


class _Connection:
    __slots__ = ("conn_id", "ws", "subscribed_tasks", "log_task_filters", "lock", "loop")

    def __init__(self, conn_id: str, ws: WebSocket) -> None:
        self.conn_id = conn_id
        self.ws = ws
        self.subscribed_tasks: set[str] = set()
        self.log_task_filters: set[str | None] = set()
        self.lock = threading.Lock()
        self.loop = asyncio.get_running_loop()

    def send_json_safe(self, data: dict[str, Any]) -> bool:
        try:
            with self.lock:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.send_json(data), self.loop
                )
                future.result(timeout=5)
            return True
        except Exception:
            return False


class WebSocketManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, _Connection] = {}
        self._subscriptions: dict[str, set[str]] = {}
        self._log_subscribers: dict[str | None, set[str]] = {}
        self._tasks_ref: dict[str, dict] | None = None

    def set_tasks_ref(self, tasks: dict[str, dict]) -> None:
        self._tasks_ref = tasks

    def _gen_conn_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def add(self, ws: WebSocket) -> str:
        conn_id = self._gen_conn_id()
        conn = _Connection(conn_id, ws)
        with self._lock:
            self._connections[conn_id] = conn
        return conn_id

    def remove(self, conn_id: str) -> None:
        with self._lock:
            conn = self._connections.pop(conn_id, None)
            if conn is None:
                return
            for task_id in conn.subscribed_tasks:
                subs = self._subscriptions.get(task_id)
                if subs is not None:
                    subs.discard(conn_id)
                    if not subs:
                        del self._subscriptions[task_id]
            for filter_key in conn.log_task_filters:
                subs = self._log_subscribers.get(filter_key)
                if subs is not None:
                    subs.discard(conn_id)
                    if not subs:
                        del self._log_subscribers[filter_key]

    def subscribe(self, conn_id: str, task_id: str) -> bool:
        with self._lock:
            conn = self._connections.get(conn_id)
            if conn is None:
                return False
            conn.subscribed_tasks.add(task_id)
            self._subscriptions.setdefault(task_id, set()).add(conn_id)
            return True

    def unsubscribe(self, conn_id: str, task_id: str) -> None:
        with self._lock:
            conn = self._connections.get(conn_id)
            if conn is None:
                return
            conn.subscribed_tasks.discard(task_id)
            subs = self._subscriptions.get(task_id)
            if subs is not None:
                subs.discard(conn_id)
                if not subs:
                    del self._subscriptions[task_id]

    def subscribe_logs(self, conn_id: str, task_id: str | None = None) -> bool:
        key: str | None = task_id or None
        with self._lock:
            conn = self._connections.get(conn_id)
            if conn is None:
                return False
            conn.log_task_filters.add(key)
            self._log_subscribers.setdefault(key, set()).add(conn_id)
            return True

    def unsubscribe_logs(self, conn_id: str, task_id: str | None = None) -> None:
        key: str | None = task_id or None
        with self._lock:
            conn = self._connections.get(conn_id)
            if conn is None:
                return
            conn.log_task_filters.discard(key)
            subs = self._log_subscribers.get(key)
            if subs is not None:
                subs.discard(conn_id)
                if not subs:
                    del self._log_subscribers[key]

    def broadcast_task_update(self, task_id: str) -> None:
        if self._tasks_ref is None:
            return
        with self._lock:
            subs = set(self._subscriptions.get(task_id, set()))
            task_snapshot = self._tasks_ref.get(task_id)
            if task_snapshot is None:
                return
            task_snapshot = dict(task_snapshot)
            connections = [self._connections[cid] for cid in subs if cid in self._connections]

        status = task_snapshot.get("status")
        event_type = "task_done" if status in ("completed", "failed", "cancelled") else "task_update"
        message = {"type": event_type, "task_id": task_id, "task": task_snapshot}

        dead: list[str] = []
        for conn in connections:
            if not conn.send_json_safe(message):
                dead.append(conn.conn_id)

        if dead:
            for cid in dead:
                self.remove(cid)

    def broadcast_log(self, record: Any) -> None:
        with self._lock:
            recipient_ids: set[str] = set()
            all_subs = self._log_subscribers.get(None)
            if all_subs:
                recipient_ids.update(all_subs)
            task_id = getattr(record, "task_id", None)
            if task_id:
                task_subs = self._log_subscribers.get(task_id)
                if task_subs:
                    recipient_ids.update(task_subs)
            connections = [self._connections[cid] for cid in recipient_ids if cid in self._connections]

        try:
            record_dict = record.model_dump()
        except AttributeError:
            record_dict = dict(record)
        message = {"type": "log", "record": record_dict}

        dead: list[str] = []
        for conn in connections:
            if not conn.send_json_safe(message):
                dead.append(conn.conn_id)

        if dead:
            for cid in dead:
                self.remove(cid)

    def has_log_subscribers(self, task_id: str | None = None) -> bool:
        key: str | None = task_id or None
        with self._lock:
            return bool(self._log_subscribers.get(key))

    def send_to(self, conn_id: str, data: dict[str, Any]) -> bool:
        with self._lock:
            conn = self._connections.get(conn_id)
        if conn is None:
            return False
        return conn.send_json_safe(data)

    def list_running_tasks(self) -> list[dict]:
        if self._tasks_ref is None:
            return []
        with self._lock:
            return [
                dict(t) for t in self._tasks_ref.values()
                if t.get("status") in ("queued", "running")
            ]

    def connection_count(self) -> int:
        with self._lock:
            return len(self._connections)

    def has_subscribers(self, task_id: str) -> bool:
        with self._lock:
            return bool(self._subscriptions.get(task_id))


ws_manager = WebSocketManager()
