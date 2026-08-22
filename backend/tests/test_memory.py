import json
from pathlib import Path
from unittest.mock import patch

import db
import memory


def _vec(*values):
    """构造 384 维向量，指定位置为 1，其余为 0。"""
    v = [0.0] * 384
    for i in values:
        v[i] = 1.0
    return v


def _setup(tmp_path: Path, ws_id: str = "ws-1"):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    conn = db._get_conn()
    conn.execute(
        "INSERT INTO workspaces (id, name, path, current) VALUES (?, ?, ?, ?)",
        (ws_id, "test", "C:/ws", 1),
    )
    # 第二个工作空间用于隔离测试
    conn.execute(
        "INSERT INTO workspaces (id, name, path, current) VALUES (?, ?, ?, ?)",
        ("ws-2", "other", "C:/ws2", 0),
    )
    conn.commit()
    conn.close()


def _insert_memory(conn, mid, ws_id, summary, vec):
    conn.execute(
        "INSERT INTO memory_entries (id, workspace_id, summary, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
        (mid, ws_id, summary, json.dumps(vec), 1.0),
    )


def test_recall_ranking_and_isolation(tmp_path: Path):
    _setup(tmp_path)
    conn = db._get_conn()
    _insert_memory(conn, "m1", "ws-1", "项目用 FastAPI", _vec(0))
    _insert_memory(conn, "m2", "ws-1", "今天天气不错", _vec(2))
    _insert_memory(conn, "m3", "ws-2", "另一个项目的记忆", _vec(0))
    conn.commit()
    conn.close()

    with patch("memory.embedding.get_embedding", return_value=_vec(0)):
        results = memory.recall_memory("FastAPI", "ws-1", top_k=5)
    assert len(results) == 2
    assert results[0]["id"] == "m1"
    # 隔离：ws-2 的记忆不被召回
    assert all(r["id"] != "m3" for r in results)


def test_recall_empty(tmp_path: Path):
    _setup(tmp_path)
    assert memory.recall_memory("hello", "ws-1") == []


def test_build_memory_context_with_memories():
    memories = [{"summary": "项目用 FastAPI"}, {"summary": "已实现 RAG"}]
    ctx = memory.build_memory_context("继续优化", memories)
    assert "项目用 FastAPI" in ctx
    assert "已实现 RAG" in ctx
    assert "继续优化" in ctx


def test_build_memory_context_empty():
    ctx = memory.build_memory_context("继续优化", [])
    assert ctx == "继续优化"


def test_list_and_delete_memory(tmp_path: Path):
    _setup(tmp_path)
    conn = db._get_conn()
    _insert_memory(conn, "m1", "ws-1", "a", _vec(0))
    conn.commit()
    conn.close()

    items = memory.list_memories("ws-1")
    assert len(items) == 1 and items[0]["id"] == "m1"
    assert memory.delete_memory("m1") is True
    assert memory.list_memories("ws-1") == []
    assert memory.delete_memory("nope") is False
