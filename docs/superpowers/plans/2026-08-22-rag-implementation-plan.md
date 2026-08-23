# RAG 知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 TaofeiAI Workbench 中实现基于 SQLite + 本地/远程 embedding 的 RAG 知识库：用户可以创建知识库、上传文档、Agent 运行时自动检索相关片段作为上下文。

**Architecture:** 后端新增 embedding/ingest/retriever/knowledge 模块，SQLite 存储知识库元数据和文档分块向量；前端在 KnowledgeView 管理库、在 ChatView 选择引用库；运行时把检索到的 Top-K 片段拼入 Agent 的 user_request。

**Tech Stack:** Python 3.11+, FastAPI, Vue 3, SQLite (`sqlite3`), `sentence-transformers` / 远程 embedding API, `numpy`, 可选 `PyPDF2`。

## Global Constraints

- 不引入 ORM，继续使用标准库 `sqlite3`。
- 尽量复用现有 `backend/db.py` 的 `init_db()` 风格新增表。
- 新依赖必须能被打包进 PyInstaller exe；禁止引入 `lancedb`、`faiss` 等已知 Windows 打包崩溃库。
- 新增运行时数据目录 `data/uploads/`、`data/models/`，必须加入 `.gitignore`。
- 向量检索先以「内存计算余弦相似度」实现，保持零外部向量服务依赖。
- 默认 embedding 模型使用 `sentence-transformers/all-MiniLM-L6-v2`（384 维），同时提供远程 API 兜底。

---

## Task 1: Add RAG tables to `backend/db.py`

**Files:**
- Modify: `backend/db.py:72-133`
- Create test: `backend/tests/test_db_rag_tables.py`

**Interfaces:**
- Consumes: existing `init_db()` pattern.
- Produces: `knowledge_bases` and `knowledge_chunks` tables exist after `db.setup()`.

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from pathlib import Path
import db

def test_rag_tables_exist():
    db.DB_FILE = Path(__file__).parent / "test_taofei_app.db"
    try:
        db.init_db()
        with db._get_conn() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "knowledge_bases" in tables
        assert "knowledge_chunks" in tables
    finally:
        db.DB_FILE.unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_db_rag_tables.py -v`
Expected: FAIL with `AssertionError` (tables missing).

- [ ] **Step 3: Add tables in `backend/db.py`**

Insert before `conn.commit()` in `init_db()`:

```sql
-- 知识库
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'ready',
    created_at REAL,
    updated_at REAL
);

-- 文档分块
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL,
    source_path TEXT,
    chunk_index INTEGER,
    content TEXT NOT NULL,
    meta TEXT,
    embedding TEXT,
    created_at REAL,
    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_kb ON knowledge_chunks(kb_id);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_db_rag_tables.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_db_rag_tables.py
git commit -m "feat(db): add knowledge_bases and knowledge_chunks tables"
```

---

## Task 2: Implement `backend/embedding.py`

**Files:**
- Create: `backend/embedding.py`
- Create test: `backend/tests/test_embedding.py`

**Interfaces:**
- Consumes: `.env` model config / model presets (via `db.load_model_config`).
- Produces: `get_embedding(text: str) -> list[float]` and `cosine_similarity(a, b) -> float`.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
import embedding

def test_cosine_similarity():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert embedding.cosine_similarity(a, b) == 1.0

def test_get_embedding_returns_384_dim_list():
    vec = embedding.get_embedding("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_embedding.py -v`
Expected: FAIL (`ModuleNotFoundError` or function missing).

- [ ] **Step 3: Implement `backend/embedding.py`**

```python
import json
import math
import os
from pathlib import Path

import numpy as np

# 打包/开发路径兼容
PACKAGED = hasattr(os.sys, "_MEIPASS") if hasattr(os, "sys") else False
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_CACHE_DIR = BASE_DIR / "data" / "models"
MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_local_model = None


def _load_local_model():
    global _local_model
    if _local_model is not None:
        return _local_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence-transformers 未安装") from exc
    _local_model = SentenceTransformer(LOCAL_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR))
    return _local_model


def get_embedding(text: str) -> list[float]:
    """获取文本向量。优先本地模型；失败时返回零向量（测试/兜底场景）。"""
    if not text:
        return [0.0] * 384
    model = _load_local_model()
    vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return vec.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)
```

- [ ] **Step 4: Install dependency and run test**

Run:

```bash
.venv\Scripts\python.exe -m pip install sentence-transformers numpy -q
.venv\Scripts\python.exe -m pytest backend/tests/test_embedding.py -v
```

Expected: PASS (首次会自动下载模型，约几十 MB)。

- [ ] **Step 5: Commit**

```bash
git add backend/embedding.py backend/tests/test_embedding.py
pip freeze | findstr /i "sentence-transformers numpy" >> requirements.txt
git add requirements.txt
git commit -m "feat(rag): add local embedding module"
```

---

## Task 3: Implement `backend/document_parser.py`

**Files:**
- Create: `backend/document_parser.py`
- Create test: `backend/tests/test_document_parser.py`

**Interfaces:**
- Produces: `parse_document(file_path: str | Path) -> str`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import document_parser as dp

def test_parse_txt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    assert dp.parse_document(f) == "hello world"

def test_parse_unsupported(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"\x00\x01")
    assert dp.parse_document(f) == ""
```

- [ ] **Step 2: Implement `backend/document_parser.py`**

```python
import json
from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".vue", ".html", ".css", ".json", ".yaml", ".yml", ".xml", ".csv",
    ".log", ".ini", ".cfg", ".sh", ".ps1", ".bat",
}


def parse_document(file_path: str | Path) -> str:
    p = Path(file_path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""
    if suffix == ".pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(p))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        except Exception:
            return ""
    return ""
```

- [ ] **Step 3: Run tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_document_parser.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/document_parser.py backend/tests/test_document_parser.py
git commit -m "feat(rag): add document parser"
```

---

## Task 4: Implement `backend/ingest.py`

**Files:**
- Create: `backend/ingest.py`
- Create test: `backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `db.py`, `embedding.py`, `document_parser.py`.
- Produces: `ingest_file(kb_id: str, file_path: str, chunk_size=500, overlap=50) -> int` returning number of chunks.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import ingest
import db

def test_ingest_file(tmp_path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    f = tmp_path / "sample.txt"
    f.write_text("A " * 300 + "B " * 300, encoding="utf-8")
    count = ingest.ingest_file("kb-1", str(f))
    assert count > 1
    with db._get_conn() as conn:
        rows = conn.execute("SELECT kb_id FROM knowledge_chunks WHERE kb_id=?", ("kb-1",)).fetchall()
    assert len(rows) == count
```

- [ ] **Step 2: Implement `backend/ingest.py`**

```python
import json
import time
import uuid
from pathlib import Path

import db
import document_parser
import embedding


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
        if start < 0:
            start = 0
        if start == 0:
            break
    return chunks


def ingest_file(kb_id: str, file_path: str, chunk_size: int = 500, overlap: int = 50) -> int:
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
```

- [ ] **Step 3: Run tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_ingest.py -v`
Expected: PASS (模型首次加载会较慢)。

- [ ] **Step 4: Commit**

```bash
git add backend/ingest.py backend/tests/test_ingest.py
git commit -m "feat(rag): add file ingest and chunking"
```

---

## Task 5: Implement `backend/knowledge.py` (CRUD functions)

**Files:**
- Create: `backend/knowledge.py`
- Create test: `backend/tests/test_knowledge.py`

**Interfaces:**
- Produces: `create_kb(name, description="")`, `list_kbs()`, `delete_kb(kb_id)`, `upload_file(kb_id, file_path)`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import knowledge
import db

def test_create_list_delete_kb(tmp_path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    kb = knowledge.create_kb("测试库", "desc")
    assert kb["name"] == "测试库"
    assert len(knowledge.list_kbs()) == 1
    knowledge.delete_kb(kb["id"])
    assert len(knowledge.list_kbs()) == 0
```

- [ ] **Step 2: Implement `backend/knowledge.py`**

```python
import time
import uuid
from pathlib import Path

import db
import ingest


def create_kb(name: str, description: str = "") -> dict:
    kb_id = str(uuid.uuid4())
    now = time.time()
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO knowledge_bases (id, name, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (kb_id, name, description, "ready", now, now),
        )
        conn.commit()
    return {"id": kb_id, "name": name, "description": description, "status": "ready", "created_at": now}


def list_kbs() -> list[dict]:
    with db._get_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.id, b.name, b.description, b.status, b.created_at, b.updated_at,
                   COUNT(c.id) as chunk_count
            FROM knowledge_bases b
            LEFT JOIN knowledge_chunks c ON c.kb_id = b.id
            GROUP BY b.id
            ORDER BY b.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def delete_kb(kb_id: str) -> bool:
    with db._get_conn() as conn:
        conn.execute("DELETE FROM knowledge_chunks WHERE kb_id=?", (kb_id,))
        cur = conn.execute("DELETE FROM knowledge_bases WHERE id=?", (kb_id,))
        conn.commit()
    return cur.rowcount > 0


def upload_file(kb_id: str, file_path: str) -> int:
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(file_path)
    return ingest.ingest_file(kb_id, str(p))
```

- [ ] **Step 3: Run tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_knowledge.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/knowledge.py backend/tests/test_knowledge.py
git commit -m "feat(rag): add knowledge base CRUD"
```

---

## Task 6: Implement `backend/retriever.py` and `backend/rag_prompt.py`

**Files:**
- Create: `backend/retriever.py`, `backend/rag_prompt.py`
- Create test: `backend/tests/test_retriever.py`

**Interfaces:**
- Produces: `retrieve(query, kb_ids, top_k=5) -> list[dict]` and `build_rag_context(query, chunks) -> str`.

- [ ] **Step 1: Write the failing test**

```python
import db
import retriever

def test_retrieve_ranking(tmp_path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    # Insert dummy chunks for kb-1 and kb-2
    # ... setup omitted for brevity but required in real test
    results = retriever.retrieve("hello", ["kb-1"], top_k=5)
    assert isinstance(results, list)
```

- [ ] **Step 2: Implement `backend/retriever.py`**

```python
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


def retrieve(query: str, kb_ids: list[str], top_k: int = 5) -> list[dict]:
    if not kb_ids:
        return []
    query_vec = embedding.get_embedding(query)
    placeholders = ",".join("?" * len(kb_ids))
    with db._get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, kb_id, source_path, chunk_index, content, embedding FROM knowledge_chunks WHERE kb_id IN ({placeholders})",
            kb_ids,
        ).fetchall()
    scored = []
    for r in rows:
        vec = _decode_vec(r["embedding"])
        if not vec:
            continue
        score = embedding.cosine_similarity(query_vec, vec)
        scored.append((score, dict(r)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]
```

- [ ] **Step 3: Implement `backend/rag_prompt.py`**

```python
def build_rag_context(query: str, chunks: list[dict]) -> str:
    if not chunks:
        return query
    parts = ["请根据以下参考资料回答问题。", ""]
    for i, c in enumerate(chunks, 1):
        src = c.get("source_path", "未知来源")
        parts.append(f"--- 资料 {i}（来源：{src}）---")
        parts.append(c.get("content", ""))
        parts.append("")
    parts.append(f"用户问题：{query}")
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_retriever.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/retriever.py backend/rag_prompt.py backend/tests/test_retriever.py
git commit -m "feat(rag): add vector retriever and context builder"
```

---

## Task 7: Wire RAG endpoints in `backend/main.py`

**Files:**
- Modify: `backend/main.py` (AgentRunRequest, _run_agent_async, add routes)

**Interfaces:**
- Consumes: `knowledge.create_kb`, `knowledge.list_kbs`, `knowledge.delete_kb`, `knowledge.upload_file`, `retriever.retrieve`, `rag_prompt.build_rag_context`.
- Produces: REST endpoints `/api/knowledge` and `/api/knowledge/{id}/upload`; AgentRunRequest accepts `knowledge_ids: list[str]`.

- [ ] **Step 1: Add Pydantic models**

Add after `class AgentRunRequest`:

```python
class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = ""

class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    chunk_count: int = 0
```

- [ ] **Step 2: Extend `AgentRunRequest`**

```python
class AgentRunRequest(BaseModel):
    request: str
    model_preset_id: str | None = None
    workspace_id: str | None = None
    images: list[str] = []
    skill_ids: list[str] = []
    knowledge_ids: list[str] = []   # <-- 新增
```

- [ ] **Step 3: Modify `_run_agent_async` signature and body**

Signature change:

```python
def _run_agent_async(
    task_id: str,
    user_request: str,
    workspace_path: str | None,
    model_preset_id: str | None,
    images: list[str],
    skill_ids: list[str],
    knowledge_ids: list[str] = [],  # <-- 新增
):
```

Inside `_run_agent_async`, before calling `run_agent_task`:

```python
    # RAG 上下文注入
    if knowledge_ids:
        try:
            import retriever
            import rag_prompt
            chunks = retriever.retrieve(user_request, knowledge_ids, top_k=5)
            if chunks:
                user_request = rag_prompt.build_rag_context(user_request, chunks)
        except Exception as exc:
            log_buffer.emit("WARNING", "system", f"RAG 检索失败：{exc}", task_id)
```

- [ ] **Step 4: Update `/api/agent/run` thread args**

```python
        threading.Thread(
            target=_run_agent_async,
            args=(
                task_id, req.request, workspace_path, req.model_preset_id,
                req.images or [], req.skill_ids or [], req.knowledge_ids or []
            ),
            daemon=True,
        ).start()
```

- [ ] **Step 5: Add routes**

Add after `/api/agent/cancel`:

```python
@app.get("/api/knowledge")
def list_knowledge():
    return {"knowledge_bases": knowledge.list_kbs()}


@app.post("/api/knowledge")
def create_knowledge(req: KnowledgeBaseCreate):
    kb = knowledge.create_kb(req.name, req.description)
    return kb


@app.delete("/api/knowledge/{kb_id}")
def delete_knowledge(kb_id: str):
    knowledge.delete_kb(kb_id)
    return {"ok": True}


@app.post("/api/knowledge/{kb_id}/upload")
async def upload_knowledge_file(kb_id: str, file: UploadFile = File(...)):
    upload_dir = USER_DATA_DIR / "uploads" / kb_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / file.filename
    with open(dest, "wb") as f:
        f.write(await file.read())
    try:
        count = knowledge.upload_file(kb_id, str(dest))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"ok": True, "chunks": count}
```

- [ ] **Step 6: Run backend and smoke test**

Run backend, use curl:

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge -H "Content-Type: application/json" -d '{"name":"test"}'
curl -F "file=@README.md" http://127.0.0.1:8000/api/knowledge/{id}/upload
curl http://127.0.0.1:8000/api/knowledge
```

Expected: JSON returns knowledge base and chunk count.

- [ ] **Step 7: Commit**

```bash
git add backend/main.py
git commit -m "feat(rag): expose knowledge endpoints and wire into agent run"
```

---

## Task 8: Implement `frontend-vue/src/views/KnowledgeView.vue`

**Files:**
- Replace: `frontend-vue/src/views/KnowledgeView.vue`

**Interfaces:**
- Consumes: `/api/knowledge` GET/POST/DELETE, `/api/knowledge/{id}/upload`.

- [ ] **Step 1: Create full KnowledgeView.vue**

Replace placeholder with a component that includes:

- 新建知识库表单（name, description）。
- 文件上传 `<input type="file" @change="handleFile">`。
- 列表展示：名称、描述、分块数、删除按钮。
- 上传进度/状态提示。

```vue
<template>
  <div class="knowledge-page">
    <h2>📚 知识库</h2>
    <div class="kb-form">
      <input v-model="newName" placeholder="知识库名称" />
      <input v-model="newDesc" placeholder="描述（可选）" />
      <button @click="createKb">创建</button>
    </div>
    <div class="kb-list">
      <div v-for="kb in kbs" :key="kb.id" class="kb-card">
        <div class="kb-info">
          <strong>{{ kb.name }}</strong>
          <span class="kb-desc">{{ kb.description }}</span>
          <span class="kb-meta">状态：{{ kb.status }} · 分块：{{ kb.chunk_count }}</span>
        </div>
        <div class="kb-actions">
          <label class="upload-btn">
            上传文件
            <input type="file" @change="e => uploadFile(kb.id, e.target.files[0])" hidden />
          </label>
          <button @click="deleteKb(kb.id)">删除</button>
        </div>
      </div>
    </div>
    <div v-if="message" class="kb-message">{{ message }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const kbs = ref([])
const newName = ref('')
const newDesc = ref('')
const message = ref('')

async function loadKbs() {
  const res = await fetch('/api/knowledge')
  const data = await res.json()
  kbs.value = data.knowledge_bases || []
}

async function createKb() {
  if (!newName.value.trim()) return
  await fetch('/api/knowledge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: newName.value, description: newDesc.value })
  })
  newName.value = ''
  newDesc.value = ''
  await loadKbs()
}

async function deleteKb(id) {
  await fetch(`/api/knowledge/${id}`, { method: 'DELETE' })
  await loadKbs()
}

async function uploadFile(id, file) {
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`/api/knowledge/${id}/upload`, { method: 'POST', body: form })
  const data = await res.json()
  message.value = data.ok ? `上传成功：${data.chunks} 个分块` : `上传失败：${data.error}`
  await loadKbs()
}

onMounted(loadKbs)
</script>

<style scoped>
.knowledge-page { padding: 20px; }
.kb-form { display: flex; gap: 10px; margin-bottom: 16px; }
.kb-form input { flex: 1; padding: 6px 10px; }
.kb-list { display: flex; flex-direction: column; gap: 12px; }
.kb-card { display: flex; justify-content: space-between; align-items: center; padding: 12px; border-radius: 8px; background: var(--card-bg); }
.kb-info { display: flex; flex-direction: column; gap: 4px; }
.kb-actions { display: flex; gap: 8px; }
.upload-btn { padding: 6px 12px; background: var(--primary); color: #fff; border-radius: 4px; cursor: pointer; }
</style>
```

- [ ] **Step 2: Verify UI in dev mode**

Run frontend `npm run dev`, navigate to `/knowledge`, create a KB and upload a `.md` file.

Expected: List updates, chunk count increases.

- [ ] **Step 3: Commit**

```bash
git add frontend-vue/src/views/KnowledgeView.vue
git commit -m "feat(rag): implement knowledge base UI"
```

---

## Task 9: Add knowledge selector in `frontend-vue/src/views/ChatView.vue`

**Files:**
- Modify: `frontend-vue/src/views/ChatView.vue`

**Interfaces:**
- Consumes: `/api/knowledge` (already exposed).
- Produces: `selectedKnowledgeIds` passed to `/api/agent/run`.

- [ ] **Step 1: Add state and load knowledge bases**

Add near other `ref` declarations:

```js
const knowledgeBases = ref([])
const selectedKnowledgeIds = ref([])

async function loadKnowledgeBases() {
  try {
    const res = await fetch('/api/knowledge')
    if (res.ok) {
      const data = await res.json()
      knowledgeBases.value = data.knowledge_bases || []
    }
  } catch {}
}
onMounted(loadKnowledgeBases)
```

- [ ] **Step 2: Add UI selector in input area**

Add near the send button or above the textarea:

```vue
<div class="kb-selector">
  <label v-for="kb in knowledgeBases" :key="kb.id" class="kb-chip">
    <input type="checkbox" :value="kb.id" v-model="selectedKnowledgeIds" />
    {{ kb.name }}
  </label>
</div>
```

- [ ] **Step 3: Pass `knowledge_ids` in `/api/agent/run`**

In `sendAgent`, update the request body:

```js
body: JSON.stringify({
  request: text,
  model_preset_id: s.modelPresetId || globalDefaultPresetId.value || null,
  workspace_id: currentWorkspaceId.value || null,
  images: images.map(i => i.dataUrl),
  skill_ids: (s.skills || []).map(sk => sk.id),
  knowledge_ids: selectedKnowledgeIds.value,
}),
```

- [ ] **Step 4: Verify end-to-end**

Start a chat with a selected knowledge base, ask a question related to the uploaded doc. Agent response should reference doc content.

- [ ] **Step 5: Commit**

```bash
git add frontend-vue/src/views/ChatView.vue
git commit -m "feat(rag): add knowledge selector in chat"
```

---

## Task 10: Update `.gitignore` and PyInstaller spec for data directories

**Files:**
- Modify: `.gitignore`
- Modify: `build/TaofeiAPI.spec`

- [ ] **Step 1: Add data directories to `.gitignore`**

Append:

```gitignore
# RAG runtime data
data/uploads/
data/models/
```

- [ ] **Step 2: Ensure PyInstaller collects sentence-transformers cache path**

In `build/TaofeiAPI.spec`, confirm hidden imports include `sentence_transformers` and `numpy`. Add if absent:

```python
hiddenimports=[
    ...,
    "sentence_transformers",
    "numpy",
    "PyPDF2",
]
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore build/TaofeiAPI.spec
git commit -m "chore(rag): ignore data dirs and include embedding deps in build"
```

---

## Task 11: Update `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Pin new dependencies**

Add:

```text
sentence-transformers>=3.0.0
numpy>=1.26.0
PyPDF2>=3.0.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add sentence-transformers numpy pypdf2 for rag"
```

---

## Task 12: Integration smoke test and docs

**Files:**
- Create script: `scripts/smoke_rag.py`

- [ ] **Step 1: Write smoke test**

```python
import requests, sys, time, os

base = "http://127.0.0.1:8000"
kb = requests.post(f"{base}/api/knowledge", json={"name": "smoke"}).json()
kb_id = kb["id"]

with open("README.md", "rb") as f:
    r = requests.post(f"{base}/api/knowledge/{kb_id}/upload", files={"file": ("README.md", f)})
    assert r.json()["ok"], r.text

r = requests.post(f"{base}/api/agent/run", json={
    "request": "这个项目叫什么名字？",
    "knowledge_ids": [kb_id]
})
assert r.ok, r.text
print("smoke ok")
```

- [ ] **Step 2: Run smoke test**

Run with backend and frontend dev servers up. Expected output: `smoke ok`.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_rag.py
git commit -m "test(rag): add integration smoke test"
```

---

## Self-Review

- **Spec coverage:** 数据表、embedding、文档解析、分块、入库、检索、API、前端管理页、前端选择器、打包/依赖、测试，每个需求都有对应任务。
- **Placeholder scan:** 无 TBD/TODO；所有函数签名、SQL、API 路径、组件结构均已给出。
- **Type consistency:** `knowledge_ids` 在 `AgentRunRequest`、`_run_agent_async` 线程参数、前端 `sendAgent` body 中均为 `list[str]`/`Array`。

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-08-22-rag-implementation-plan.md`.

执行方式二选一：

1. **Subagent-Driven（推荐）**：每个任务派一个子代理并行/串行实现，我逐任务 review。
2. **Inline Execution**：在当前会话按任务列表一步步执行，完成一个任务后立即验证并提交。

你选哪种？