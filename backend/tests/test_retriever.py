import json
from pathlib import Path
from unittest.mock import patch

import db
import rag_prompt
import retriever


def test_build_rag_context_with_chunks():
    chunks = [
        {"source_path": "doc.md", "content": "这是第一段资料"},
        {"source_path": "code.py", "content": "这是第二段资料"},
    ]
    ctx = rag_prompt.build_rag_context("项目叫什么？", chunks)
    assert "doc.md" in ctx
    assert "code.py" in ctx
    assert "项目叫什么？" in ctx
    assert ctx.startswith("请根据以下参考资料回答问题")


def test_build_rag_context_empty_chunks():
    ctx = rag_prompt.build_rag_context("项目叫什么？", [])
    assert ctx == "项目叫什么？"


def _vec(*values):
    """构造 384 维向量，指定位置为 1，其余为 0。"""
    v = [0.0] * 384
    for i in values:
        v[i] = 1.0
    return v


def _insert_chunk(conn, kb_id, chunk_id, content, vec):
    conn.execute(
        """
        INSERT INTO knowledge_chunks
        (id, kb_id, source_path, chunk_index, content, meta, embedding, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (chunk_id, kb_id, "doc.md", 0, content, "{}", json.dumps(vec), 1.0),
    )


def test_retrieve_ranking(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    conn = db._get_conn()
    conn.execute(
        "INSERT INTO knowledge_bases (id, name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("kb-1", "test", "ready", 1.0, 1.0),
    )
    # 两个分块：c1 与 mock query 向量（第 0 维为 1）完全一致，c2 正交
    _insert_chunk(conn, "kb-1", "c1", "Python 是一种编程语言", _vec(0))
    _insert_chunk(conn, "kb-1", "c2", "今天天气不错", _vec(2))
    conn.commit()
    conn.close()

    with patch("retriever.embedding.get_embedding", return_value=_vec(0)):
        results = retriever.retrieve("Python 编程", ["kb-1"], top_k=5)
    assert len(results) == 2
    # 相关度高的排前面
    assert results[0]["id"] == "c1"
    assert results[0]["source_path"] == "doc.md"


def test_retrieve_empty_kb_ids(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    assert retriever.retrieve("hello", []) == []
