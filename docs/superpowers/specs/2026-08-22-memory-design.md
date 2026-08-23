# 跨会话向量记忆（Memory）设计文档

**日期**：2026-08-22
**分支**：feature/rag（延续 RAG 基建）
**状态**：已批准，待实现

## 目标

为 TaofeiAI Workbench 开启「跨会话长期语义记忆」：Agent 任务完成后自动生成摘要并向量化入库；新任务开始时，基于当前问题在**同一工作空间**内做向量召回，把最相关的历史记忆注入 prompt，让 Agent 记得之前做过什么。

本设计只做**跨会话语义记忆 + 精确召回**，不包含会话内逐字历史注入。

## 设计原则

- **best-effort**：记忆是辅助功能，任何环节失败都不得影响主 Agent 任务。
- **复用 RAG 基建**：`embedding.py`（384 维向量）、`knowledge_chunks` 同款向量存储格式、`retriever.py` 余弦排序思路全部直接复用。
- **按工作空间隔离**：`memory_entries.workspace_id` 归属 `workspaces.id`，A 工作空间的记忆不会被 B 工作空间召回。
- **零新依赖**：不引入任何新第三方库（摘要生成复用现有 `llm_call`，向量化复用 `embedding.py`）。

## 架构

```
写入路径（任务 completed 后）:
  Agent 任务结束（status=completed）
    ├─► LLM 生成记忆摘要（请求 + 结论 + 关键事实，JSON）
    ├─► embedding 向量化（384 维）
    └─► 存 SQLite memory_entries（含 workspace_id）

召回路径（任务开始前）:
  新 Agent 任务（memory_enabled=true 且存在 workspace_id）
    ├─► query 向量化
    ├─► 在该 workspace 的记忆中余弦召回 Top-K（默认 5）
    └─► 拼入 system prompt ──► Agent 回答
```

## 数据模型（`backend/db.py` 新增）

```sql
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    embedding TEXT NOT NULL,
    created_at REAL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memory_ws ON memory_entries(workspace_id);
```

- `embedding`：JSON 数组字符串（与 `knowledge_chunks.embedding` 格式一致，384 维）。
- 工作空间删除时记忆级联删除（与 `knowledge_chunks` 的 FK 行为一致）。

## 摘要结构

每次保存用固定 prompt 让 LLM 输出 JSON：

```json
{
  "summary": "一句话总结用户请求与结论",
  "facts": ["关键事实1", "关键事实2"]
}
```

入库时 `summary` 字段存 `summary + "\n" + "；".join(facts)`（合并后整体向量化、整体注入）。LLM 输出非法 JSON 或字段缺失时，按错误处理降级，不写库。

## 模块划分

| 文件 | 职责 |
|------|------|
| `backend/db.py` | 新增 `memory_entries` 表 + 索引 |
| `backend/memory.py`（新增） | `save_memory()`（摘要生成 + 向量化 + 入库）、`recall_memory()`（向量召回）、`list_memories()`、`delete_memory()` |
| `backend/main.py` | `_run_agent_async` 任务开始前召回注入、完成后写入；`/api/memory` 接口；`AgentRunRequest.memory_enabled` |
| `frontend-vue/src/views/ChatView.vue` | 输入区「🧠 记忆」开关 |
| `backend/prompts.py`（新增，可选） | 摘要生成 prompt 模板（与 rag_prompt.py 分离） |

## 核心函数签名

`backend/memory.py`：

```python
def save_memory(llm_call, workspace_id: str, user_request: str, final_answer: str) -> bool:
    """任务完成后调用：LLM 摘要 → 向量化 → 入库。失败返回 False 不抛出。"""

def recall_memory(query: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """任务开始前调用：向量召回该工作空间最相关的 Top-K 条记忆。
    返回 [{"summary": str, "created_at": float, "id": str}, ...]"""

def build_memory_context(query: str, memories: list[dict]) -> str:
    """把召回的记忆拼装为注入文本；无记忆时返回原 query。"""

def list_memories(workspace_id: str, limit: int = 50) -> list[dict]:
    """管理接口：列出某工作空间的记忆。"""

def delete_memory(memory_id: str) -> bool:
    """管理接口：删除单条记忆。"""
```

## 摘要生成 prompt（`backend/prompts.py`）

```
你是记忆提炼助手。根据【用户请求】和【Agent 结论】，提取一条可长期复用的记忆。
要求：
1. summary：一句话总结请求与核心结论（不超过 80 字）
2. facts：列出 1-3 条可被未来引用的具体事实（路径、技术选型、决策、结果等）
只输出 JSON，格式：{"summary": "...", "facts": ["...", "..."]}
```

## 接入点（`backend/main.py` 的 `_run_agent_async`）

**签名变更**：新增 `workspace_id: str | None = None` 参数（`agent_run` 传入 `req.workspace_id`），与现有 `workspace_path` 并列。

**任务开始前（召回注入，位于 RAG 注入之后）**：

```python
memory_ctx = user_request
if memory_enabled and workspace_path:
    try:
        memories = memory.recall_memory(user_request, workspace_id, top_k=5)
        if memories:
            memory_ctx = memory.build_memory_context(user_request, memories)
            log_buffer.emit("INFO", "system", f"已注入 {len(memories)} 条相关记忆", task_id)
    except Exception as exc:
        log_buffer.emit("WARNING", "system", f"记忆召回失败：{exc}", task_id)
user_request = memory_ctx  # 注入失败时保持原请求
```

**任务完成后（写入，仅 status=completed）**：

```python
if final_status == "completed" and memory_enabled and workspace_path:
    try:
        memory.save_memory(llm_call, workspace_id, user_request, final_text)
    except Exception as exc:
        log_buffer.emit("WARNING", "system", f"记忆保存失败：{exc}", task_id)
```

> `workspace_id` 由 `agent_run` 把 `req.workspace_id` 透传给 `_run_agent_async`（新增参数），与现有 `workspace_path` 并列；未选择工作空间（空值）时不启用记忆。

## 前端开关交互（`ChatView.vue`）

- 位置：输入区，知识库选择条上方，独立「🧠 记忆」chip 开关。
- 状态：`localStorage` key `memoryEnabled`，全局偏好，默认 `true`。
- 状态机：
  - 已选工作空间 → 可点击，`🧠 记忆：开/关`；点击切换并写 localStorage，下次任务生效。
  - 未选工作空间 → 置灰禁用，tooltip「选择工作空间后可用记忆」。
  - 开 + 发送 → 请求带 `memory_enabled: true`（后端召回 + 写入）。
  - 关 + 发送 → 请求带 `memory_enabled: false`（后端完全不读不写）。
- 反馈：注入成功 emit「已注入 N 条相关记忆」；写入成功 emit「已保存 1 条新记忆」；异常 emit warning（走现有时间线日志展示，不改 UI 结构）。

## API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agent/run` | `AgentRunRequest` 新增 `memory_enabled: bool = True` |
| GET | `/api/memory?workspace_id=xxx&limit=50` | 列出某工作空间记忆（管理用） |
| DELETE | `/api/memory/{id}` | 删除单条记忆 |

前端管理页（列出/删除记忆）本期不做，只暴露后端 API。

## 错误处理

**总原则：best-effort，任何环节失败不影响主 Agent 任务。**

| 环节 | 失败场景 | 处理 |
|------|----------|------|
| 召回注入 | embedding 失败 / DB 异常 | `try/except`，emit warning，跳过注入，用原始 prompt |
| 召回注入 | 工作空间无记忆 | 静默跳过（正常路径） |
| 摘要生成 | LLM 失败 / 超时 / 非 JSON | 复用 `llm_call` 线程池超时保护；失败仅 warning，不写库 |
| 写入 | embedding 失败 / SQLite 异常 | 跳过本条，emit warning |
| 任务取消/失败 | cancelled / failed | 不写入记忆 |
| 注入后任务失败 | 记忆误导 | 归因主流程，由主流程错误处理接管 |

## 测试

- `backend/tests/test_memory.py`：
  - `save_memory` 成功写入（mock LLM 返回合法 JSON、mock embedding）
  - `save_memory` LLM 返回非法 JSON → 不写库、返回 False
  - `recall_memory` 按相关性排序（mock embedding，同 retriever 测试手法）
  - `recall_memory` 跨工作空间隔离（A 空间记忆不被 B 空间召回）
  - `build_memory_context` 有/无记忆两种输出
  - `list_memories` / `delete_memory` 基本行为
- 集成：复用 `scripts/smoke_rag.py` 模式新增 `scripts/smoke_memory.py`，验证「保存 → 召回 → 注入」全链路（mock LLM 摘要，真实 embedding）。

## 范围（本期不做）

- 会话内逐字历史注入
- 记忆管理前端页面（仅后端 API）
- 记忆去重/合并/遗忘策略（先自然增长，必要时后续加清理）
- 记忆条数上限与淘汰（首版不做，靠工作空间隔离控制规模）

## 交付物清单

- `backend/db.py`（+表）
- `backend/memory.py`（新增）
- `backend/prompts.py`（新增）
- `backend/main.py`（接入 + 接口）
- `frontend-vue/src/views/ChatView.vue`（开关）
- `backend/tests/test_memory.py`（新增）
- `scripts/smoke_memory.py`（新增）
