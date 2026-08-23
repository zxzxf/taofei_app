"""RAG 文档入库模块。

职责：
- 把文档解析为文本后按固定长度 + 重叠切片。
- 对每个分块生成 embedding，写入 SQLite knowledge_chunks 表。
"""

import json
import time
import uuid

import db
import document_parser
import embedding


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """按固定长度 + 重叠切分文本，返回分块列表。"""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        new_start = end - overlap
        if new_start <= start:
            new_start = start + 1  # 防止死循环
        start = new_start
    return chunks


def ingest_file(kb_id: str, file_path: str, chunk_size: int = 500, overlap: int = 50) -> int:
    """解析文件、分块、向量化并写入 knowledge_chunks，返回分块数量。"""
    text = document_parser.parse_document(file_path)
    if not text:
        return 0
    chunks = chunk_text(text, chunk_size, overlap)
    now = time.time()
    with db._get_conn() as conn:
        for idx, content in enumerate(chunks):
            vec = embedding.get_embedding(content)
            conn.execute(
                """
                INSERT INTO knowledge_chunks
                (id, kb_id, source_path, chunk_index, content, meta, embedding, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    kb_id,
                    str(file_path),
                    idx,
                    content,
                    json.dumps({"chunk_size": chunk_size, "overlap": overlap}, ensure_ascii=False),
                    json.dumps(vec, ensure_ascii=False),
                    now,
                ),
            )
        conn.execute(
            "UPDATE knowledge_bases SET status=?, updated_at=? WHERE id=?",
            ("ready", now, kb_id),
        )
        conn.commit()
    return len(chunks)
