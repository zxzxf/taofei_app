# 跨会话向量记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 CrewAI Workbench 中实现按工作空间隔离的跨会话向量记忆：任务完成后自动摘要入库，新任务按相似度召回历史记忆注入 prompt。

**Architecture:** 复用 RAG 基建（`embedding.py` 384 维向量 + SQLite 向量存储 + 余弦召回）；新增 `memory_entries` 表和 `memory.py` 模块；`_run_agent_async` 任务开始前召回注入、完成后写入；前端 ChatView 增加记忆开关。

**Tech Stack:** Python 3.10+, FastAPI, Vue 3, SQLite (`sqlite3`), 现有 `sentence-transformers` / `embedding.py`, 现有 `llm_call`。

## Global Constraints

- 不引入 ORM 与任何新第三方库；摘要生成复用现有 `llm_call`，向量化复用 `embedding.py`。
- **best-effort**：记忆相关代码全部包在独立 `try/except` 中，任何失败只 emit warning，不得影响主 Agent 任务。
- 按工作空间隔离：`memory_entries.workspace_id` 非空，外键指向 `workspaces(id)`，级联删除。
- `embedding` 字段为 JSON 数组字符串，384 维，与 `knowledge_chunks` 格式一致。
- 测试运行方式：`$env:PYTHONPATH='<repo>\backend'; .venv\Scripts\python.exe -m pytest <path> -v`
- 记忆只对 `status=completed` 的任务写入；cancelled/failed 不写入。

---

## Task 1: Add `memory_entries` table to `backend/db.py`

**Files:**
- Modify: `backend/db.py`（`init_db()` 中，`knowledge_chunks` 表之后）
- Test: `backend/tests/test_db_memory_table.py`

**Interfaces:**
- Consumes: 现有 `init_db()` / `_get_conn()` 模式。
- Produces: `db.setup()` 后 `memory_entries` 表与 `idx_memory_ws` 索引存在。

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import db


def test_memory_table_exists():
    db.DB_FILE = Path(__file__).parent / "test_memory_db.db"
    conn = None
    try:
        db.init_db()
        conn = db._get_conn()
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "memory_entries" in tables
        assert "idx_memory_ws" in indexes
    finally:
        if conn is not None:
            conn.close()
        try:
            db.DB_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='d:\workspaces\taofei_plateform\taofei_app\backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_db_memory_table.py -v`
Expected: FAIL（`memory_entries` 不在 tables 集合中）。

- [ ] **Step 3: Add table in `backend/db.py`**

在 `init_db()` 的 `knowledge_chunks` 建表之后、`conn.commit()` 之前插入：

```python
        # 跨会话记忆（按工作空间隔离）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at REAL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_ws ON memory_entries(workspace_id)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: 同 Step 2
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_db_memory_table.py
git commit -m "feat(memory): add memory_entries table"
```

---

## Task 2: Implement recall / list / delete in `backend/memory.py`

**Files:**
- Create: `backend/memory.py`
- Test: `backend/tests/test_memory.py`

**Interfaces:**
- Consumes: `db._get_conn()`、`embedding.get_embedding()`、`embedding.cosine_similarity()`（复用 RAG 基建）。
- Produces:
  - `recall_memory(query: str, workspace_id: str, top_k: int = 5) -> list[dict]`，元素为 `{"id", "summary", "created_at"}`
  - `build_memory_context(query: str, memories: list[dict]) -> str`
  - `list_memories(workspace_id: str, limit: int = 50) -> list[dict]`
  - `delete_memory(memory_id: str) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path
from unittest.mock import patch

import db
import memory


def _vec(*values):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='d:\workspaces\taofei_plateform\taofei_app\backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_memory.py -v`
Expected: FAIL（`memory` 模块不存在）。

- [ ] **Step 3: Implement `backend/memory.py`**

```python
"""跨会话向量记忆模块。

职责：
- 任务完成后保存记忆：LLM 摘要 → 向量化 → 入库（save_memory，见 Task 3）。
- 任务开始前召回：按工作空间做向量余弦召回（recall_memory）。
- 管理：list_memories / delete_memory。
设计原则：best-effort，任何失败只返回空/False，不抛出影响主流程。
"""

import json

import db
import embedding


def _decode_vec(raw) -> list[float] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def recall_memory(query: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """召回指定工作空间与 query 最相关的 Top-K 条记忆。"""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: 同 Step 2
Expected: 6 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/memory.py backend/tests/test_memory.py
git commit -m "feat(memory): add recall, context builder, list and delete"
```

---

## Task 3: Implement `save_memory` and summary prompt

**Files:**
- Create: `backend/prompts.py`
- Modify: `backend/memory.py`（追加 `save_memory`）
- Modify: `backend/tests/test_memory.py`（追加 save_memory 用例）

**Interfaces:**
- Consumes: `llm_call(messages: list[dict]) -> str`（现有闭包，线程池超时保护）、`embedding.get_embedding()`、`db._get_conn()`。
- Produces: `save_memory(llm_call, workspace_id: str, user_request: str, final_answer: str) -> bool`

- [ ] **Step 1: Create `backend/prompts.py`**

```python
"""集中管理的 prompt 模板（与 rag_prompt.py 分离，避免 main.py 膨胀）。"""

MEMORY_SUMMARY_SYSTEM = (
    "你是记忆提炼助手。根据【用户请求】和【Agent 结论】，提取一条可长期复用的记忆。"
    "要求：\n"
    "1. summary：一句话总结请求与核心结论（不超过 80 字）\n"
    "2. facts：列出 1-3 条可被未来引用的具体事实（路径、技术选型、决策、结果等）\n"
    "只输出 JSON，格式：{\"summary\": \"...\", \"facts\": [\"...\", \"...\"]}"
)


def build_memory_summary_messages(user_request: str, final_answer: str) -> list[dict]:
    """构造摘要生成的 messages。final_answer 超长时截断，避免 token 浪费。"""
    answer = final_answer if final_answer else "（无结论）"
    if len(answer) > 4000:
        answer = answer[:4000] + "…"
    return [
        {"role": "system", "content": MEMORY_SUMMARY_SYSTEM},
        {"role": "user", "content": f"【用户请求】\n{user_request}\n\n【Agent 结论】\n{answer}"},
    ]
```

- [ ] **Step 2: Write the failing tests（追加到 `backend/tests/test_memory.py`）**

```python
import json as _json


def _fake_llm(content: str):
    def llm_call(messages):
        return content
    return llm_call


def test_save_memory_success(tmp_path: Path):
    _setup(tmp_path)
    llm = _fake_llm(_json.dumps({"summary": "项目用 FastAPI", "facts": ["后端在 backend/main.py"]}, ensure_ascii=False))
    with patch("memory.embedding.get_embedding", return_value=_vec(0)):
        ok = memory.save_memory(llm, "ws-1", "分析技术栈", "结论：FastAPI")
    assert ok is True
    items = memory.list_memories("ws-1")
    assert len(items) == 1
    assert "FastAPI" in items[0]["summary"]
    assert "backend/main.py" in items[0]["summary"]


def test_save_memory_invalid_json(tmp_path: Path):
    _setup(tmp_path)
    llm = _fake_llm("这不是 JSON")
    with patch("memory.embedding.get_embedding", return_value=_vec(0)):
        ok = memory.save_memory(llm, "ws-1", "q", "a")
    assert ok is False
    assert memory.list_memories("ws-1") == []


def test_save_memory_missing_workspace(tmp_path: Path):
    _setup(tmp_path)
    llm = _fake_llm(_json.dumps({"summary": "x", "facts": []}))
    with patch("memory.embedding.get_embedding", return_value=_vec(0)):
        ok = memory.save_memory(llm, "", "q", "a")
    assert ok is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$env:PYTHONPATH='d:\workspaces\taofei_plateform\taofei_app\backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_memory.py -v`
Expected: 新增 3 个用例 FAIL（`save_memory` 未定义）。

- [ ] **Step 4: Implement `save_memory`（追加到 `backend/memory.py`）**

```python
import json
import time
import uuid

import prompts


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
```

> 注意：`prompts` 是 `backend/` 下的新模块，测试与 `main.py` 均以 `PYTHONPATH=backend` 或 `sys.path` 方式导入，与 `db`/`embedding` 一致。

- [ ] **Step 5: Run tests to verify they pass**

Run: 同 Step 3
Expected: 全部 PASS（含 Task 2 的 6 个用例）。

- [ ] **Step 6: Commit**

```bash
git add backend/prompts.py backend/memory.py backend/tests/test_memory.py
git commit -m "feat(memory): add save_memory with LLM summary"
```

---

## Task 4: Wire memory into `backend/main.py`

**Files:**
- Modify: `backend/main.py`（`AgentRunRequest`、`_run_agent_async`、`agent_run`、新增 `/api/memory` 路由）

**Interfaces:**
- Consumes: `memory.recall_memory`、`memory.build_memory_context`、`memory.save_memory`、`memory.list_memories`、`memory.delete_memory`。
- Produces: `AgentRunRequest.memory_enabled: bool = True`；`_run_agent_async(..., knowledge_ids=None, workspace_id=None, memory_enabled=True)`；路由 `/api/memory` GET/DELETE。

- [ ] **Step 1: Extend `AgentRunRequest`（`main.py` 中 `knowledge_ids` 之后）**

```python
    memory_enabled: bool = True  # 是否启用跨会话记忆（召回 + 写入）
```

- [ ] **Step 2: Extend `_run_agent_async` 签名与记忆注入**

签名改为：

```python
def _run_agent_async(task_id, user_request, workspace_path, model_preset_id, images=None, skill_ids=None, knowledge_ids=None, workspace_id=None, memory_enabled=True):
```

在 `_run_agent_async` 内、RAG 注入代码块之后追加召回注入：

```python
        # 跨会话记忆注入：同工作空间向量召回
        if memory_enabled and workspace_id:
            try:
                import memory
                memories = memory.recall_memory(user_request, workspace_id, top_k=5)
                if memories:
                    user_request = memory.build_memory_context(user_request, memories)
                    log_buffer.emit("INFO", "system", f"已注入 {len(memories)} 条相关记忆", task_id)
            except Exception as exc:
                log_buffer.emit("WARNING", "system", f"记忆召回失败：{exc}", task_id)
```

- [ ] **Step 3: 在 `run_agent_task(...)` 调用之后追加记忆写入**

```python
        run_agent_task(
            task_id=task_id,
            user_request=user_request,
            llm_call=llm_call,
            workspace_path=workspace_path,
            emit_log=emit_log,
            task_store=_tasks,
            task_lock=_tasks_lock,
            notify_update=notify_update,
            images=images or [],
            skills=bound_skills,
            cancel_flag_getter=lambda: _task_cancel.get(task_id, False),
        )

        # 跨会话记忆写入：仅 completed 且启用记忆时保存
        if memory_enabled and workspace_id:
            try:
                import memory
                with _tasks_lock:
                    task = _tasks.get(task_id, {})
                    if task.get("status") == "completed":
                        result = task.get("result")
                        final_text = result if isinstance(result, str) else ""
                        if isinstance(result, dict):
                            final_text = (result.get("summary") or result.get("content") or "")
                if final_text:
                    saved = memory.save_memory(llm_call, workspace_id, user_request, str(final_text))
                    if saved:
                        log_buffer.emit("INFO", "system", "已保存 1 条新记忆", task_id)
            except Exception as exc:
                log_buffer.emit("WARNING", "system", f"记忆保存失败：{exc}", task_id)
```

- [ ] **Step 4: Update `agent_run` 线程参数**

```python
    threading.Thread(
        target=_run_agent_async,
        args=(
            task_id, req.request, workspace_path, req.model_preset_id,
            req.images or [], req.skill_ids or [], req.knowledge_ids or [],
            req.workspace_id or None, req.memory_enabled,
        ),
        daemon=True,
    ).start()
```

- [ ] **Step 5: Add `/api/memory` routes（知识库路由之后）**

```python
# ---------------------------------------------------------------
# 跨会话记忆
# ---------------------------------------------------------------
@app.get("/api/memory")
def list_memory(workspace_id: str = Query(""), limit: int = Query(50, ge=1, le=200)):
    """列出某工作空间的记忆（管理用）。"""
    import memory
    if not workspace_id:
        return JSONResponse({"error": "workspace_id 不能为空"}, status_code=400)
    return {"memories": memory.list_memories(workspace_id, limit)}


@app.delete("/api/memory/{memory_id}")
def delete_memory(memory_id: str):
    """删除单条记忆。"""
    import memory
    ok = memory.delete_memory(memory_id)
    if not ok:
        return JSONResponse({"error": "记忆不存在"}, status_code=404)
    return {"ok": True}
```

- [ ] **Step 6: 语法与导入验证**

Run: `.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'd:\workspaces\taofei_plateform\taofei_app\backend'); import main; print('ok')"`
Expected: 输出 `ok`，无异常。

- [ ] **Step 7: Commit**

```bash
git add backend/main.py
git commit -m "feat(memory): wire memory recall and save into agent run"
```

---

## Task 5: Add memory toggle in `ChatView.vue`

**Files:**
- Modify: `frontend-vue/src/views/ChatView.vue`

**Interfaces:**
- Consumes: `/api/agent/run`（已支持 `memory_enabled`）。
- Produces: 输入区「🧠 记忆」开关；请求体携带 `memory_enabled`。

- [ ] **Step 1: Add state（`selectedKnowledgeIds` 声明之后）**

```js
const memoryEnabled = ref(localStorage.getItem('memoryEnabled') !== 'false')
watch(memoryEnabled, (v) => {
  localStorage.setItem('memoryEnabled', String(v))
})
```

> 确认 `watch` 已在 `import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'` 中（已在）。

- [ ] **Step 2: Add toggle UI（知识库选择条上方）**

在 `<div v-if="knowledgeBases.length" class="chat-kb-row">` 之前插入：

```vue
        <div class="chat-memory-row">
          <label class="chat-memory-chip" :class="{ disabled: !currentWorkspaceId }" :title="currentWorkspaceId ? '跨会话记忆：任务结束后自动记住结论，下次可召回' : '选择工作空间后可用记忆'">
            <input type="checkbox" v-model="memoryEnabled" :disabled="!currentWorkspaceId" />
            🧠 记忆：{{ memoryEnabled && currentWorkspaceId ? '开' : '关' }}
          </label>
        </div>
```

- [ ] **Step 3: Pass `memory_enabled` in `/api/agent/run` 请求体**

```js
      body: JSON.stringify({
        request: text,
        model_preset_id: s.modelPresetId || globalDefaultPresetId.value || null,
        workspace_id: currentWorkspaceId.value || null,
        images: images.map(i => i.dataUrl),
        skill_ids: (s.skills || []).map(sk => sk.id),
        knowledge_ids: selectedKnowledgeIds.value,
        memory_enabled: memoryEnabled.value && !!currentWorkspaceId.value,
      }),
```

- [ ] **Step 4: Add styles（`chat-kb-row` 样式块附近）**

```css
.chat-memory-row {
  display: flex;
  align-items: center;
  padding: 6px 4px 0;
}
.chat-memory-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--bg-soft);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all .15s;
  user-select: none;
}
.chat-memory-chip:hover:not(.disabled) {
  border-color: var(--primary);
}
.chat-memory-chip.disabled {
  opacity: .45;
  cursor: not-allowed;
}
.chat-memory-chip input {
  accent-color: var(--primary);
  margin: 0;
  cursor: pointer;
}
.chat-memory-chip:has(input:checked) {
  border-color: var(--primary);
  background: rgba(59, 130, 246, 0.12);
  color: var(--primary);
}
```

- [ ] **Step 5: Verify build**

Run: `cd frontend-vue; npm run build`
Expected: `✓ built` 无报错。

- [ ] **Step 6: Commit**

```bash
git add frontend-vue/src/views/ChatView.vue
git commit -m "feat(memory): add memory toggle in chat input"
```

---

## Task 6: Integration smoke test

**Files:**
- Create: `scripts/smoke_memory.py`

**Interfaces:**
- Consumes: `db`、`memory`、`embedding`（直接模块级调用，无需起服务）。
- Produces: 验证「保存 → 召回 → 注入 → 隔离」全链路。

- [ ] **Step 1: Write the smoke script**

```python
"""记忆功能集成冒烟测试（模块级，无需启动服务）。

用法：.venv\\Scripts\\python.exe scripts/smoke_memory.py
"""

import json
import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import db
import memory
import embedding

tmp = pathlib.Path(tempfile.mkdtemp()) / "smoke.db"
db.DB_FILE = tmp
db.setup()

# 准备两个工作空间
conn = db._get_conn()
conn.execute("INSERT INTO workspaces (id, name, path, current) VALUES ('ws-a', 'A', 'C:/a', 1)")
conn.execute("INSERT INTO workspaces (id, name, path, current) VALUES ('ws-b', 'B', 'C:/b', 0)")
conn.commit()
conn.close()

print("[1/4] 保存记忆（mock LLM 摘要）")
def fake_llm(messages):
    return json.dumps({"summary": "taofei_app 使用 CrewAI + FastAPI", "facts": ["SQLite 持久化", "RAG 已实现"]}, ensure_ascii=False)

ok = memory.save_memory(fake_llm, "ws-a", "分析技术栈", "结论：CrewAI + FastAPI")
assert ok, "保存失败"
print("  ok: 已保存 1 条")

print("[2/4] 同工作空间召回")
hits = memory.recall_memory("项目用什么框架", "ws-a", top_k=5)
assert hits and "CrewAI" in hits[0]["summary"], hits
print(f"  ok: 命中 {len(hits)} 条，首条含 CrewAI")

print("[3/4] 跨工作空间隔离")
hits_b = memory.recall_memory("项目用什么框架", "ws-b", top_k=5)
assert hits_b == [], hits_b
print("  ok: ws-b 未召回 ws-a 的记忆")

print("[4/4] 上下文拼装与清理")
ctx = memory.build_memory_context("继续优化", hits)
assert "继续优化" in ctx and "CrewAI" in ctx
memory.delete_memory(hits[0]["id"])
assert memory.list_memories("ws-a") == []
print("  ok: 上下文拼装正常，删除成功")

print("\nSMOKE OK")
```

- [ ] **Step 2: Run the smoke script**

Run: `.venv\Scripts\python.exe scripts/smoke_memory.py`
Expected: 输出 `SMOKE OK`（embedding 模型首次加载会慢，属正常）。

- [ ] **Step 3: Run full unit tests**

Run: `$env:PYTHONPATH='d:\workspaces\taofei_plateform\taofei_app\backend'; .venv\Scripts\python.exe -m pytest backend/tests/ -v`
Expected: 全部 PASS（原有 RAG 用例 + 新增 memory 用例）。

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_memory.py
git commit -m "test(memory): add integration smoke test"
```

---

## Self-Review

- **Spec coverage**：数据表（Task 1）、召回/上下文/管理（Task 2）、摘要生成+写入（Task 3）、main.py 接入与接口（Task 4）、前端开关（Task 5）、集成测试（Task 6），全部覆盖。
- **Placeholder scan**：无 TBD/TODO；所有函数签名、SQL、代码块均完整给出。
- **Type consistency**：`save_memory(llm_call, workspace_id, user_request, final_answer) -> bool`、`recall_memory(query, workspace_id, top_k=5) -> list[dict]`、`build_memory_context(query, memories) -> str`、`list_memories(workspace_id, limit=50)`、`delete_memory(memory_id) -> bool` 在 Task 2/3/4/6 中保持一致；`memory_enabled` 在请求模型、线程参数、前端 body 中均为 bool。
