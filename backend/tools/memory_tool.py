"""memory_tool.py —— 记忆管理工具（memory_save / memory_recall / memory_forget / memory_list）。

基于 memory.py 的向量记忆能力，封装为 Agent 可主动调用的工具：
- memory_save：保存一条事实/经验到长期记忆
- memory_recall：按关键词/语义召回相关记忆
- memory_forget：删除指定记忆
- memory_list：列出当前工作空间的记忆列表

设计原则：
- 任何异常都返回 error 文本，不抛出
- memory_save 不需要 LLM 摘要（Agent 自己组织好内容传进来），直接向量化入库
- 记忆作用域：当前工作空间
- 自动去重：相同/高度相似的内容不重复保存（余弦相似度 > 0.95 视为重复）
"""

from __future__ import annotations

import json
import time
import uuid

import db
import embedding

# 相似度阈值：超过此值视为重复记忆，不重复保存
_DUP_THRESHOLD = 0.95


# ---------------------------------------------------------------
# 核心实现
# ---------------------------------------------------------------

def _get_workspace_id(workspace_path: str | None) -> str:
    """根据 workspace_path 查 workspace_id；查不到返回空串。"""
    if not workspace_path:
        return ""
    try:
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM workspaces WHERE path = ? LIMIT 1",
                (workspace_path,),
            ).fetchone()
        return row["id"] if row else ""
    except Exception:
        return ""


def memory_save(workspace_path: str | None, content: str, kind: str = "episodic") -> dict:
    """保存一条记忆到当前工作空间。

    Args:
        workspace_path: 工作空间路径（用于定位 workspace_id）
        content: 记忆内容（Agent 组织好的事实/经验文本，直接保存）
        kind: 记忆类型，默认 episodic（情景记忆）

    Returns:
        {"observation": "成功描述...", "error": ""} 或 {"observation": "", "error": "..."}
    """
    content = (content or "").strip()
    if not content:
        return {"observation": "", "error": "记忆内容不能为空。"}

    ws_id = _get_workspace_id(workspace_path)
    if not ws_id:
        return {"observation": "", "error": f"未找到工作空间：{workspace_path}"}

    try:
        # 生成向量，查重
        vec = embedding.get_embedding(content)
        with db._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, summary, embedding FROM memory_entries WHERE workspace_id = ? AND kind = ?",
                (ws_id, kind or "episodic"),
            ).fetchall()

        for r in rows:
            try:
                existing_vec = json.loads(r["embedding"]) if r["embedding"] else []
            except Exception:
                continue
            if not existing_vec:
                continue
            sim = embedding.cosine_similarity(vec, existing_vec)
            if sim >= _DUP_THRESHOLD:
                return {
                    "observation": f"已存在高度相似的记忆（相似度 {sim:.2f}），跳过重复保存。\n"
                                   f"已有记忆：{r['summary'][:100]}",
                    "error": "",
                }

        # 写入新记忆
        mem_id = str(uuid.uuid4())
        now = time.time()
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO memory_entries (id, workspace_id, summary, embedding, created_at, kind) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mem_id, ws_id, content, json.dumps(vec, ensure_ascii=False), now, kind or "episodic"),
            )
            conn.commit()

        return {"observation": f"记忆已保存（ID: {mem_id[:8]}…），共 {len(content)} 字。", "error": ""}
    except Exception as e:
        return {"observation": "", "error": f"保存记忆失败：{type(e).__name__}: {e}"}


def memory_recall(workspace_path: str | None, query: str, top_k: int = 5) -> dict:
    """按语义召回相关记忆。

    Args:
        workspace_path: 工作空间路径
        query: 查询文本
        top_k: 返回最相关的 Top-K 条（默认 5，最大 20）

    Returns:
        {"observation": "召回结果文本...", "error": ""}
    """
    query = (query or "").strip()
    if not query:
        return {"observation": "", "error": "查询内容不能为空。"}

    ws_id = _get_workspace_id(workspace_path)
    if not ws_id:
        return {"observation": "当前无工作空间，暂无记忆。", "error": ""}

    try:
        top_k = max(1, min(int(top_k), 20))
    except Exception:
        top_k = 5

    try:
        # 复用 memory.recall_memory 逻辑（内联实现避免循环导入）
        query_vec = embedding.get_embedding(query)
        with db._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, summary, embedding, created_at, kind FROM memory_entries WHERE workspace_id = ?",
                (ws_id,),
            ).fetchall()

        scored: list[tuple[float, dict]] = []
        for r in rows:
            try:
                vec = json.loads(r["embedding"]) if r["embedding"] else []
            except Exception:
                continue
            if not vec:
                continue
            score = embedding.cosine_similarity(query_vec, vec)
            scored.append((score, {
                "id": r["id"],
                "summary": r["summary"],
                "created_at": r["created_at"],
                "kind": r["kind"] if "kind" in r.keys() else "episodic",
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [item for _, item in scored[:top_k]]

        if not results:
            return {"observation": "暂无相关记忆。", "error": ""}

        lines = [f"召回 {len(results)} 条相关记忆（按相关度排序）：", ""]
        for i, m in enumerate(results, 1):
            kind_label = {"user_profile": "用户画像", "workspace_fact": "工作空间事实",
                          "episodic": "情景记忆"}.get(m.get("kind", ""), "记忆")
            lines.append(f"[{i}] {kind_label}（ID: {m['id'][:8]}…）")
            lines.append(f"    内容：{m['summary']}")
            lines.append("")

        return {"observation": "\n".join(lines).rstrip("\n"), "error": ""}
    except Exception as e:
        return {"observation": "", "error": f"召回记忆失败：{type(e).__name__}: {e}"}


def memory_forget(workspace_path: str | None, memory_id: str = "", keyword: str = "") -> dict:
    """删除指定记忆。

    支持两种方式（二选一）：
    - memory_id：精确删除某条记忆
    - keyword：删除内容包含该关键词的所有记忆（慎用）

    Args:
        workspace_path: 工作空间路径
        memory_id: 要删除的记忆 ID（前缀匹配也可，只要唯一）
        keyword: 按关键词删除（memory_id 为空时生效）

    Returns:
        {"observation": "删除了 N 条记忆", "error": ""}
    """
    ws_id = _get_workspace_id(workspace_path)
    if not ws_id:
        return {"observation": "", "error": f"未找到工作空间：{workspace_path}"}

    try:
        with db._get_conn() as conn:
            if memory_id:
                # 支持前缀匹配
                row = conn.execute(
                    "SELECT id, summary FROM memory_entries WHERE workspace_id = ? AND id LIKE ?",
                    (ws_id, memory_id + "%"),
                ).fetchone()
                if not row:
                    return {"observation": "", "error": f"未找到记忆 ID：{memory_id}"}
                actual_id = row["id"]
                cur = conn.execute("DELETE FROM memory_entries WHERE id = ?", (actual_id,))
                conn.commit()
                return {
                    "observation": f"已删除 1 条记忆：{row['summary'][:80]}",
                    "error": "",
                }
            elif keyword:
                keyword = keyword.strip()
                cur = conn.execute(
                    "DELETE FROM memory_entries WHERE workspace_id = ? AND summary LIKE ?",
                    (ws_id, f"%{keyword}%"),
                )
                conn.commit()
                n = cur.rowcount
                return {"observation": f"已删除 {n} 条含关键词「{keyword}」的记忆。", "error": ""}
            else:
                return {"observation": "", "error": "请提供 memory_id 或 keyword 参数。"}
    except Exception as e:
        return {"observation": "", "error": f"删除记忆失败：{type(e).__name__}: {e}"}


def memory_list(workspace_path: str | None, limit: int = 20, kind: str = "") -> dict:
    """列出当前工作空间的记忆。

    Args:
        workspace_path: 工作空间路径
        limit: 返回条数（默认 20，最大 100）
        kind: 按类型过滤（episodic / workspace_fact / user_profile），空则全部

    Returns:
        {"observation": "记忆列表文本...", "error": ""}
    """
    ws_id = _get_workspace_id(workspace_path)
    if not ws_id:
        return {"observation": "当前无工作空间，暂无记忆。", "error": ""}

    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20

    try:
        with db._get_conn() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT id, summary, created_at, kind FROM memory_entries "
                    "WHERE workspace_id = ? AND kind = ? ORDER BY created_at DESC LIMIT ?",
                    (ws_id, kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, summary, created_at, kind FROM memory_entries "
                    "WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                    (ws_id, limit),
                ).fetchall()

        if not rows:
            return {"observation": "暂无记忆。", "error": ""}

        kind_labels = {
            "user_profile": "用户画像",
            "workspace_fact": "工作空间事实",
            "episodic": "情景记忆",
        }

        lines = [f"共 {len(rows)} 条记忆（按时间倒序）：", ""]
        for i, r in enumerate(rows, 1):
            label = kind_labels.get(r["kind"], r["kind"] or "记忆")
            lines.append(f"[{i}] {label}（ID: {r['id'][:8]}…）")
            lines.append(f"    内容：{r['summary'][:150]}")
            lines.append("")

        return {"observation": "\n".join(lines).rstrip("\n"), "error": ""}
    except Exception as e:
        return {"observation": "", "error": f"列出记忆失败：{type(e).__name__}: {e}"}


# ---------------------------------------------------------------
# 注册到工具中心
# ---------------------------------------------------------------

def _memory_save_handler(workspace, args, **_kwargs):
    return memory_save(
        workspace,
        content=str(args.get("content", "")),
        kind=str(args.get("kind", "episodic")),
    )


def _memory_recall_handler(workspace, args, **_kwargs):
    try:
        top_k = int(args.get("top_k", 5))
    except Exception:
        top_k = 5
    return memory_recall(
        workspace,
        query=str(args.get("query", "")),
        top_k=top_k,
    )


def _memory_forget_handler(workspace, args, **_kwargs):
    return memory_forget(
        workspace,
        memory_id=str(args.get("memory_id", "")),
        keyword=str(args.get("keyword", "")),
    )


def _memory_list_handler(workspace, args, **_kwargs):
    try:
        limit = int(args.get("limit", 20))
    except Exception:
        limit = 20
    return memory_list(
        workspace,
        limit=limit,
        kind=str(args.get("kind", "")),
    )


def _check_embedding_available() -> bool:
    """检查 embedding 能力是否可用（本地模型或 fallback 任一即可）。"""
    try:
        import embedding
        if hasattr(embedding, "is_available"):
            return bool(embedding.is_available())
        # 旧版本兼容：直接测试一次 get_embedding
        v = embedding.get_embedding("test")
        return isinstance(v, list) and len(v) > 0
    except Exception:
        return False


try:
    from .registry import registry

    # memory_save
    registry.register(
        name="memory_save",
        description=(
            "保存一条事实/经验到当前工作空间的长期记忆。"
            "记忆会被向量化，之后可以用语义搜索召回。"
            "适合保存：项目约定、用户偏好、重要发现、踩过的坑、解决方案等。"
            "自动去重：高度相似（>0.95）的内容不会重复保存。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要保存的记忆内容（组织成清晰的事实/经验文本）",
                },
                "kind": {
                    "type": "string",
                    "description": "记忆类型：episodic（情景记忆，默认）/ workspace_fact（工作空间事实）",
                    "default": "episodic",
                    "enum": ["episodic", "workspace_fact"],
                },
            },
            "required": ["content"],
        },
        handler=_memory_save_handler,
        tags=["default", "memory"],
        check_fn=_check_embedding_available,
    )

    # memory_recall
    registry.register(
        name="memory_recall",
        description=(
            "从当前工作空间的长期记忆中，按语义召回与查询最相关的记忆。"
            "当你需要回忆之前保存过的信息、用户偏好、项目约定时使用。"
            "返回 Top-K 条最相关的记忆及其内容。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "查询文本，描述你想回忆的内容",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回最相关的条数（默认 5，最大 20）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_memory_recall_handler,
        tags=["default", "memory"],
        check_fn=_check_embedding_available,
    )

    # memory_forget
    registry.register(
        name="memory_forget",
        description=(
            "删除记忆。支持两种方式："
            "1）通过 memory_id 删除单条记忆（推荐，精确）；"
            "2）通过 keyword 删除所有包含该关键词的记忆（慎用，会批量删除）。"
            "当记忆过时、错误或不再需要时使用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "要删除的记忆 ID（前缀匹配即可，如 memory_list 返回的 ID 前 8 位）",
                },
                "keyword": {
                    "type": "string",
                    "description": "按关键词批量删除（memory_id 为空时生效）",
                },
            },
            "required": [],
        },
        handler=_memory_forget_handler,
        tags=["default", "memory"],
        check_fn=_check_embedding_available,
    )

    # memory_list
    registry.register(
        name="memory_list",
        description=(
            "列出当前工作空间的记忆（按时间倒序）。"
            "可以查看有哪些记忆、了解记忆库的整体情况。"
            "支持按类型过滤和限制返回条数。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回条数（默认 20，最大 100）",
                    "default": 20,
                },
                "kind": {
                    "type": "string",
                    "description": "按类型过滤：episodic / workspace_fact / user_profile，空则返回全部",
                    "default": "",
                },
            },
            "required": [],
        },
        handler=_memory_list_handler,
        tags=["default", "memory"],
        check_fn=_check_embedding_available,
    )

except Exception:
    pass  # registry 不可用时跳过注册
