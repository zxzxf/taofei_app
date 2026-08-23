"""RAG 检索模块。

职责：
- 对 query 生成 embedding，在指定知识库的所有分块中做余弦相似度排序。
- 返回 Top-K 分块（含来源与原文），供 rag_prompt 拼装上下文。
"""

import json

import db
import embedding


def _decode_vec(raw) -> list[float] | None:
    """把数据库里的向量 JSON 字符串解码为 list[float]。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def retrieve(query: str, kb_ids: list[str], top_k: int = 5) -> list[dict]:
    """在指定知识库中检索与 query 最相关的 Top-K 分块。

    返回的每个 dict 包含：id, kb_id, source_path, chunk_index, content, meta。
    """
    if not kb_ids or not query:
        return []
    query_vec = embedding.get_embedding(query)
    placeholders = ",".join("?" * len(kb_ids))
    with db._get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, kb_id, source_path, chunk_index, content, meta, embedding
            FROM knowledge_chunks
            WHERE kb_id IN ({placeholders})
            """,
            kb_ids,
        ).fetchall()

    scored: list[tuple[float, dict]] = []
    for r in rows:
        vec = _decode_vec(r["embedding"])
        if not vec:
            continue
        score = embedding.cosine_similarity(query_vec, vec)
        item = {
            "id": r["id"],
            "kb_id": r["kb_id"],
            "source_path": r["source_path"],
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "meta": r["meta"],
        }
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]
