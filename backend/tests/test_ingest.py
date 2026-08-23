import sqlite3
from pathlib import Path

import db
import ingest


def test_chunk_text_basic():
    text = "A" * 300 + "B" * 300
    chunks = ingest.chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    # 首块含 A，末块含 B
    assert "A" in chunks[0]
    assert "B" in chunks[-1]
    # 相邻块有重叠
    assert chunks[0][-40:] == chunks[1][:40]


def test_chunk_text_small_text():
    chunks = ingest.chunk_text("hello", chunk_size=500, overlap=50)
    assert chunks == ["hello"]


def test_chunk_text_empty():
    assert ingest.chunk_text("") == []


def test_ingest_file(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    # 先创建知识库记录以满足外键约束
    conn = db._get_conn()
    conn.execute(
        "INSERT INTO knowledge_bases (id, name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("kb-1", "sample", "ready", 1.0, 1.0),
    )
    conn.commit()
    conn.close()
    f = tmp_path / "sample.txt"
    f.write_text("A " * 300 + "B " * 300, encoding="utf-8")
    count = ingest.ingest_file("kb-1", str(f), chunk_size=200, overlap=40)
    assert count > 1
    conn = db._get_conn()
    try:
        rows = conn.execute(
            "SELECT kb_id, chunk_index FROM knowledge_chunks WHERE kb_id=?", ("kb-1",)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == count
    # 分块索引连续
    indexes = sorted(r["chunk_index"] for r in rows)
    assert indexes == list(range(count))


def test_ingest_missing_file(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    count = ingest.ingest_file("kb-1", str(tmp_path / "nope.txt"))
    assert count == 0
