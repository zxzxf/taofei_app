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


def clear_workspace_memories(workspace_id: str) -> int:
    """清除指定工作空间的全部记忆，返回删除条数。"""
    if not workspace_id:
        return 0
    with db._get_conn() as conn:
        cur = conn.execute("DELETE FROM memory_entries WHERE workspace_id=?", (workspace_id,))
        conn.commit()
    return cur.rowcount or 0


def save_memory(llm_call, workspace_id: str, user_request: str, final_answer: str, kind: str = "episodic") -> bool:
    """任务完成后调用：LLM 摘要 → 向量化 → 入库。失败返回 False，不抛出。

    kind：记忆分型标签，默认 'episodic'（情景记忆）；写库时一并记录，
    旧调用方不带该参数时行为保持不变。
    """
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
                "INSERT INTO memory_entries (id, workspace_id, summary, embedding, created_at, kind) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), workspace_id, summary, json.dumps(vec, ensure_ascii=False), now, kind or "episodic"),
            )
            conn.commit()
        return True
    except Exception:
        return False


# -------------------------------------------------------------
# 用户长期画像（kind='user_profile'，全局仅一条，覆盖式维护）
# -------------------------------------------------------------
_USER_PROFILE_PROMPT_SYSTEM = (
    "你是用户画像分析师。根据【用户请求】与【助手回答】推断用户的稳定偏好、身份与工作习惯，"
    "例如：常用语言与表达风格、职业/角色、技术栈与工具偏好、沟通与工作方式等。\n"
    "要求：\n"
    "1. 只提取稳定、可跨会话复用的特征，忽略一次性任务细节；\n"
    "2. 输出一段不超过 300 字的中文用户画像描述；\n"
    "3. 只输出 JSON，格式：{\"profile\": \"用户画像描述\"}"
)


def _extract_json_obj(raw: str) -> dict | None:
    """容错解析 LLM 输出的 JSON 对象：容忍 ```json 代码块包裹及前后杂质。"""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    # 兜底：截取首个 { 到最后一个 } 之间的内容再解析
    s, e = raw.find("{"), raw.rfind("}")
    if 0 <= s < e:
        try:
            data = json.loads(raw[s : e + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def upsert_user_profile(llm_call, user_request: str, final_answer: str) -> dict:
    """从本轮对话提炼用户长期画像并覆盖式入库（全局仅一条 kind='user_profile'）。

    流程：LLM 抽取 JSON → 解析成功后才 DELETE 旧画像 + INSERT 新画像（同事务）。
    成功返回 {'ok': True, 'profile': str}；LLM 输出非法或入库失败返回 {'ok': False}，绝不抛出。
    注意：本函数只做直接 SQL 写入，不涉及向量 embedding。
    """
    try:
        answer = (final_answer or "")[:4000] if final_answer else "（无结论）"
        messages = [
            {"role": "system", "content": _USER_PROFILE_PROMPT_SYSTEM},
            {"role": "user", "content": f"【用户请求】\n{user_request}\n\n【助手回答】\n{answer}"},
        ]
        raw = llm_call(messages)
        data = _extract_json_obj(raw)
        if not data:
            return {"ok": False}
        profile = (data.get("profile") or "").strip()
        if not profile:
            return {"ok": False}
        profile = profile[:300]
        with db._get_conn() as conn:
            # 画像行须满足外键约束：挂靠库中最早创建的工作区。
            # 读取侧（build_user_profile_context 等）一律按 kind 过滤，不依赖 workspace_id 取值。
            ws = conn.execute(
                "SELECT id FROM workspaces ORDER BY rowid ASC LIMIT 1"
            ).fetchone()
            ws_id = ws["id"] if ws else ""
            conn.execute("DELETE FROM memory_entries WHERE kind = 'user_profile'")
            # embedding 列 NOT NULL 且画像不经向量召回，写入空向量 '[]' 占位
            conn.execute(
                "INSERT INTO memory_entries (id, workspace_id, summary, embedding, created_at, kind) "
                "VALUES (?, ?, ?, '[]', ?, 'user_profile')",
                (str(uuid.uuid4()), ws_id, profile, time.time()),
            )
            conn.commit()
        return {"ok": True, "profile": profile}
    except Exception:
        return {"ok": False}


def build_user_profile_context() -> str:
    """返回可注入 prompt 的长期用户画像文本；尚未建立画像时返回空串。"""
    try:
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT summary FROM memory_entries WHERE kind = 'user_profile' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row or not row["summary"]:
            return ""
        return "以下是你对用户的长期了解（自动维护）：\n" + row["summary"]
    except Exception:
        return ""
