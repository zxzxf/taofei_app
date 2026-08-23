"""知识库管理模块。

职责：
- 知识库的创建、列表、删除。
- 文件上传并触发入库（委托 ingest 模块）。
"""

import time
import uuid
from pathlib import Path

import db
import ingest


def create_kb(name: str, description: str = "") -> dict:
    """创建知识库，返回知识库记录。"""
    kb_id = str(uuid.uuid4())
    now = time.time()
    with db._get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_bases (id, name, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (kb_id, name, description, "ready", now, now),
        )
        conn.commit()
    return {
        "id": kb_id,
        "name": name,
        "description": description,
        "status": "ready",
        "chunk_count": 0,
        "created_at": now,
        "updated_at": now,
    }


def list_kbs() -> list[dict]:
    """列出所有知识库及各自分块数量。"""
    with db._get_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.id, b.name, b.description, b.status, b.created_at, b.updated_at,
                   COUNT(c.id) AS chunk_count
            FROM knowledge_bases b
            LEFT JOIN knowledge_chunks c ON c.kb_id = b.id
            GROUP BY b.id
            ORDER BY b.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def delete_kb(kb_id: str) -> bool:
    """删除知识库及其全部分块，返回是否删除成功。"""
    with db._get_conn() as conn:
        conn.execute("DELETE FROM knowledge_chunks WHERE kb_id=?", (kb_id,))
        cur = conn.execute("DELETE FROM knowledge_bases WHERE id=?", (kb_id,))
        conn.commit()
    return cur.rowcount > 0


def upload_file(kb_id: str, file_path: str) -> int:
    """上传文件到知识库并触发入库，返回分块数量。"""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(file_path)
    return ingest.ingest_file(kb_id, str(p))
