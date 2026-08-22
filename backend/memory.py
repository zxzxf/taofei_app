"""跨会话向量记忆模块。

职责：
- 任务完成后保存记忆：LLM 摘要 → 向量化 → 入库（save_memory，见 Task 3）。
- 任务开始前召回：按工作空间做向量余弦召回（recall_memory）。
- 管理：list_memories / delete_memory。

设计原则：best-effort，任何失败只返回空/False，不抛出影响主流程。
"""

import json
import time
import uuid

import db
import embedding
import prompts


def _decode_vec(raw) -> list[float] | None:
    """把数据库里的向量 JSON 字符串解码为 list[float]。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def recall_memory(query: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """召回指定工作空间与 query 最相关的 Top-K 条记忆。

    返回的每个 dict 包含：id, summary, created_at。
    """
    if not query or not workspace_id:
        return []
    query_vec = embedding.get_embedding(query)
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT id, summary, embedding, created_at FROM memory_entries WHERE workspace_id=?",
            (workspace_id,),
        ).fetchall()
    scored: list[tuple[float, dict]] = []
    for r in rows:
        vec = _decode_vec(r["embedding"])
        if not vec:
            continue
        score = embedding.cosine_similarity(query_vec, vec)
        scored.append((score, {
            "id": r["id"],
            "summary": r["summary"],
            "created_at": r["created_at"],
        }))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def build_memory_context(query: str, memories: list[dict]) -> str:
    """把召回的记忆拼装为注入文本；无记忆时原样返回 query。"""
    if not memories:
        return query
    parts = [
        "以下是你此前在同项目中的历史记忆（可能与当前问题相关，供参考，不要虚构）：", ""
    ]
    for i, m in enumerate(memories, 1):
        parts.append(f"[记忆 {i}] {m.get('summary', '')}")
        parts.append("")
    parts.append(f"当前用户问题：{query}")
    return "\n".join(parts)


def list_memories(workspace_id: str, limit: int = 50) -> list[dict]:
    """列出某工作空间的记忆（按时间倒序）。"""
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT id, summary, created_at FROM memory_entries WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_memory(memory_id: str) -> bool:
    """删除单条记忆。"""
    with db._get_conn() as conn:
        cur = conn.execute("DELETE FROM memory_entries WHERE id=?", (memory_id,))
        conn.commit()
    return cur.rowcount > 0


def save_memory(llm_call, workspace_id: str, user_request: str, final_answer: str) -> bool:
    """任务完成后调用：LLM 摘要 → 向量化 → 入库。失败返回 False，不抛出。"""
    if not workspace_id or not user_request:
        return False
    try:
        raw = llm_call(prompts.build_memory_summary_messages(user_request, final_answer))
        raw = (raw or "").strip()
        # 兼容 LLM 输出被代码块包裹
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        if not isinstance(data, dict):
            return False
        summary = (data.get("summary") or "").strip()
        facts = data.get("facts")
        if not summary:
            return False
        if isinstance(facts, list):
            summary += "\n" + "；".join(str(f) for f in facts if f)
        vec = embedding.get_embedding(summary)
        now = time.time()
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO memory_entries (id, workspace_id, summary, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), workspace_id, summary, json.dumps(vec, ensure_ascii=False), now),
            )
            conn.commit()
        return True
    except Exception:
        return False
