"""taofei_app 本地数据持久化层（SQLite）。

职责：
- 把原本分散在 JSON 文件中的用户数据（模型配置、预设、工作区、技能、工作流）
  统一存到一个 SQLite 数据库文件中。
- 数据库文件位于用户数据目录，卸载应用时不会丢失。
- 首次启动时自动从旧 JSON 文件迁移数据。

设计原则：
- 不引入 ORM，直接使用标准库 sqlite3，保持零依赖。
- 对外暴露的接口尽量和原 JSON 读写函数保持一致，降低 main.py 改动成本。
"""

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

# -------------------------------------------------------------
# 路径规划：与 backend/main.py 保持一致
# -------------------------------------------------------------
PACKAGED = hasattr(sys, "_MEIPASS")
if PACKAGED:
    _BASE_DIR = Path(sys._MEIPASS)
    _EXE_DIR = Path(sys.executable).parent
    if sys.platform == "win32":
        USER_DATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "taofei_app"
    elif sys.platform == "darwin":
        USER_DATA_DIR = Path.home() / "Library/Application Support/taofei_app"
    else:
        USER_DATA_DIR = Path.home() / ".config/taofei_app"
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent
    _EXE_DIR = _BASE_DIR
    USER_DATA_DIR = _BASE_DIR

DB_FILE = USER_DATA_DIR / "taofei_app.db"

_JSON_FILES = {
    "model_config": USER_DATA_DIR / "model_config.json",
    "model_presets": USER_DATA_DIR / "model_presets.json",
    "workspaces": USER_DATA_DIR / "workspaces.json",
    "skills": USER_DATA_DIR / "skills.json",
    "workflows": USER_DATA_DIR / "workflows.json",
}

# 打包模式下 exe 同目录可能残留旧 JSON，迁移时从这里兜底复制
_OLD_EXE_JSON_FILES = {
    "model_config": _EXE_DIR / "model_config.json",
    "model_presets": _EXE_DIR / "model_presets.json",
    "workspaces": _EXE_DIR / "workspaces.json",
    "skills": _EXE_DIR / "skills.json",
    "workflows": _EXE_DIR / "workflows.json",
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def init_db() -> None:
    """创建所有表和索引。幂等，可安全重复调用。"""
    with _get_conn() as conn:
        # 当前激活模型配置（key-value，兼容原来的 JSON 结构）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # 模型预设
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                base_url TEXT,
                api_key TEXT,
                created_at TEXT
            )
        """)

        # 当前激活预设 ID（单记录表，id 恒为 1）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_preset (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                preset_id TEXT
            )
        """)
        conn.execute("INSERT OR IGNORE INTO active_preset (id, preset_id) VALUES (1, '')")

        # 工作区
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT,
                path TEXT UNIQUE,
                current INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ws_path ON workspaces(path)")

        # 技能（字段不固定，整体存 JSON）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)

        # 工作流（字段不固定，整体存 JSON）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)

        # 知识库
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'ready',
                created_at REAL,
                updated_at REAL
            )
        """)

        # 文档分块
        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_kb ON knowledge_chunks(kb_id)")

        # 跨会话记忆（按工作空间隔离）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at REAL,
                kind TEXT DEFAULT 'episodic',
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_ws ON memory_entries(workspace_id)")
        # 老库迁移：对已存在的 memory_entries 表补充 kind 列（新库建表已含该列，此处会失败并被忽略）
        try:
            conn.execute("ALTER TABLE memory_entries ADD COLUMN kind TEXT DEFAULT 'episodic'")
        except Exception:
            pass

        # 对话会话（Session 化架构：跨请求持久的对话上下文）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新对话',
                workspace_id TEXT,
                model_preset_id TEXT,
                skill_ids TEXT,
                knowledge_ids TEXT,
                memory_enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id)")

        # 会话消息（OpenAI 兼容原生格式，逐条存 JSON）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_messages (
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_call_id TEXT,
                tool_calls TEXT,
                PRIMARY KEY (session_id, seq)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sm_session ON session_messages(session_id)")

        # 会话全文检索（FTS5）。老版 SQLite 未编译 FTS5 时创建会失败，捕获后跳过，
        # 此时 search_sessions 会自动降级为 LIKE 检索，不影响其它功能。
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(session_id UNINDEXED, role, content)"
            )
        except Exception:
            pass

        conn.commit()


def _load_json_file(path: Path) -> Any:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _migrate_from_json() -> None:
    """从旧 JSON 文件迁移数据到 SQLite（仅首次）。

    迁移完成后会把旧 JSON 文件重命名为 *.backup.json，避免重复迁移。
    """
    if not DB_FILE.exists():
        return  # 数据库还不存在，init_db 会创建

    # 打包模式下，先把 exe 同目录的旧 JSON 复制到用户数据目录（如果用户数据目录还没有）
    if PACKAGED:
        for name, src in _OLD_EXE_JSON_FILES.items():
            dst = _JSON_FILES[name]
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

    # model_config
    cfg_path = _JSON_FILES["model_config"]
    if cfg_path.exists():
        data = _load_json_file(cfg_path)
        if isinstance(data, dict):
            with _get_conn() as conn:
                for k, v in data.items():
                    if isinstance(v, str):
                        conn.execute(
                            "INSERT OR REPLACE INTO model_config (key, value) VALUES (?, ?)",
                            (k, v),
                        )
                conn.commit()
        shutil.move(cfg_path, cfg_path.with_suffix(".backup.json"))

    # model_presets
    presets_path = _JSON_FILES["model_presets"]
    if presets_path.exists():
        data = _load_json_file(presets_path)
        if isinstance(data, dict):
            presets = data.get("presets", [])
            active_id = data.get("active_id", "")
            if isinstance(presets, list):
                with _get_conn() as conn:
                    for p in presets:
                        if not isinstance(p, dict):
                            continue
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO model_presets
                            (id, name, provider, model, base_url, api_key, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                p.get("id", ""),
                                p.get("name", ""),
                                p.get("provider", ""),
                                p.get("model", ""),
                                p.get("base_url", ""),
                                p.get("api_key", ""),
                                p.get("created_at", ""),
                            ),
                        )
                    conn.execute(
                        "INSERT OR REPLACE INTO active_preset (id, preset_id) VALUES (1, ?)",
                        (active_id,),
                    )
                    conn.commit()
        shutil.move(presets_path, presets_path.with_suffix(".backup.json"))

    # workspaces
    ws_path = _JSON_FILES["workspaces"]
    if ws_path.exists():
        data = _load_json_file(ws_path)
        if isinstance(data, dict):
            workspaces = data.get("workspaces", [])
            current_id = data.get("current_id")
            if isinstance(workspaces, list):
                with _get_conn() as conn:
                    seen_paths = set()
                    for ws in workspaces:
                        if not isinstance(ws, dict):
                            continue
                        path = ws.get("path", "")
                        if not path or path in seen_paths:
                            continue
                        seen_paths.add(path)
                        conn.execute(
                            "INSERT OR REPLACE INTO workspaces (id, name, path, current) VALUES (?, ?, ?, ?)",
                            (
                                ws.get("id", ""),
                                ws.get("name", ""),
                                path,
                                1 if ws.get("id") == current_id else 0,
                            ),
                        )
                    conn.commit()
        shutil.move(ws_path, ws_path.with_suffix(".backup.json"))

    # skills
    skills_path = _JSON_FILES["skills"]
    if skills_path.exists():
        data = _load_json_file(skills_path)
        if isinstance(data, list):
            with _get_conn() as conn:
                for s in data:
                    if isinstance(s, dict) and s.get("id"):
                        conn.execute(
                            "INSERT OR REPLACE INTO skills (id, data) VALUES (?, ?)",
                            (s["id"], json.dumps(s, ensure_ascii=False)),
                        )
                conn.commit()
        shutil.move(skills_path, skills_path.with_suffix(".backup.json"))

    # workflows
    wf_path = _JSON_FILES["workflows"]
    if wf_path.exists():
        data = _load_json_file(wf_path)
        if isinstance(data, list):
            with _get_conn() as conn:
                for w in data:
                    if isinstance(w, dict) and w.get("id"):
                        conn.execute(
                            "INSERT OR REPLACE INTO workflows (id, data) VALUES (?, ?)",
                            (w["id"], json.dumps(w, ensure_ascii=False)),
                        )
                conn.commit()
        shutil.move(wf_path, wf_path.with_suffix(".backup.json"))


def setup() -> None:
    """初始化数据库并执行一次性迁移。"""
    init_db()
    _migrate_from_json()
    # 会话全文索引全量重建（Hermes 能力补齐 D4；表不存在时静默跳过）
    try:
        rebuild_session_fts()
    except Exception:
        pass


# -------------------------------------------------------------
# model_config
# -------------------------------------------------------------
def load_model_config(defaults: dict[str, str]) -> dict[str, str]:
    """读取模型配置，缺失字段用 defaults 补齐。"""
    cfg = dict(defaults)
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM model_config").fetchall()
            for row in rows:
                k = row["key"]
                if k in cfg and isinstance(row["value"], str):
                    cfg[k] = row["value"].strip()
    except Exception:
        pass
    return cfg


def save_model_config(cfg: dict[str, str]) -> None:
    """保存模型配置。"""
    try:
        with _get_conn() as conn:
            for k, v in cfg.items():
                conn.execute(
                    "INSERT OR REPLACE INTO model_config (key, value) VALUES (?, ?)",
                    (k, str(v)),
                )
            conn.commit()
    except Exception as exc:
        # 避免循环导入：main.py 中的 log_buffer 无法在这里使用，直接打印
        print(f"[ERROR] 保存模型配置失败：{exc}", flush=True)


# -------------------------------------------------------------
# model_presets
# -------------------------------------------------------------
def load_presets() -> dict:
    """读取模型预设列表与当前激活预设 ID。"""
    default: dict = {"presets": [], "active_id": ""}
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT id, name, provider, model, base_url, api_key, created_at "
                "FROM model_presets ORDER BY created_at"
            ).fetchall()
            default["presets"] = [_row_to_dict(r) for r in rows]
            active_row = conn.execute("SELECT preset_id FROM active_preset WHERE id = 1").fetchone()
            if active_row:
                default["active_id"] = active_row["preset_id"] or ""
    except Exception:
        pass
    return default


def save_presets(data: dict) -> None:
    """保存模型预设列表与当前激活预设 ID。"""
    try:
        presets = data.get("presets", [])
        active_id = data.get("active_id", "")
        with _get_conn() as conn:
            # 简单策略：清空后重新写入
            conn.execute("DELETE FROM model_presets")
            for p in presets:
                if not isinstance(p, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO model_presets
                    (id, name, provider, model, base_url, api_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p.get("id", ""),
                        p.get("name", ""),
                        p.get("provider", ""),
                        p.get("model", ""),
                        p.get("base_url", ""),
                        p.get("api_key", ""),
                        p.get("created_at", ""),
                    ),
                )
            conn.execute(
                "INSERT OR REPLACE INTO active_preset (id, preset_id) VALUES (1, ?)",
                (active_id,),
            )
            conn.commit()
    except Exception as exc:
        print(f"[ERROR] 保存模型预设失败：{exc}", flush=True)


def get_preset_api_key(preset_id: str) -> str:
    """获取指定预设的原始 API Key。"""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT api_key FROM model_presets WHERE id = ?", (preset_id,)
            ).fetchone()
            return row["api_key"] if row else ""
    except Exception:
        return ""


# -------------------------------------------------------------
# workspaces
# -------------------------------------------------------------
def load_workspaces() -> dict:
    """读取工作空间配置。"""
    default = {"current_id": None, "workspaces": []}
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT id, name, path, current FROM workspaces").fetchall()
            workspaces = []
            current_id = None
            for r in rows:
                ws = {"id": r["id"], "name": r["name"], "path": r["path"]}
                workspaces.append(ws)
                if r["current"]:
                    current_id = r["id"]
            default["workspaces"] = workspaces
            default["current_id"] = current_id
    except Exception:
        pass
    return default


def save_workspaces(data: dict) -> None:
    """保存工作空间配置。"""
    try:
        workspaces = data.get("workspaces", [])
        current_id = data.get("current_id")
        with _get_conn() as conn:
            conn.execute("DELETE FROM workspaces")
            seen_paths = set()
            for ws in workspaces:
                if not isinstance(ws, dict):
                    continue
                path = ws.get("path", "")
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)
                conn.execute(
                    "INSERT OR REPLACE INTO workspaces (id, name, path, current) VALUES (?, ?, ?, ?)",
                    (
                        ws.get("id", ""),
                        ws.get("name", ""),
                        path,
                        1 if ws.get("id") == current_id else 0,
                    ),
                )
            conn.commit()
    except Exception as exc:
        print(f"[ERROR] 保存工作空间失败：{exc}", flush=True)


# -------------------------------------------------------------
# skills
# -------------------------------------------------------------
def load_skills() -> list[dict]:
    """读取技能列表。"""
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT data FROM skills").fetchall()
            skills = []
            for r in rows:
                try:
                    s = json.loads(r["data"])
                    if isinstance(s, dict):
                        skills.append(s)
                except Exception:
                    pass
            return skills
    except Exception:
        return []


def save_skills(skills: list[dict]) -> None:
    """保存技能列表。"""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM skills")
            for s in skills:
                if isinstance(s, dict) and s.get("id"):
                    conn.execute(
                        "INSERT INTO skills (id, data) VALUES (?, ?)",
                        (s["id"], json.dumps(s, ensure_ascii=False)),
                    )
            conn.commit()
    except Exception as exc:
        print(f"[ERROR] 保存技能配置失败：{exc}", flush=True)


# -------------------------------------------------------------
# workflows
# -------------------------------------------------------------
def load_workflows() -> list[dict]:
    """读取工作流列表。"""
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT data FROM workflows").fetchall()
            items = []
            for r in rows:
                try:
                    w = json.loads(r["data"])
                    if isinstance(w, dict):
                        items.append(w)
                except Exception:
                    pass
            return items
    except Exception:
        return []


def save_workflows(items: list[dict]) -> None:
    """保存工作流列表。"""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM workflows")
            for w in items:
                if isinstance(w, dict) and w.get("id"):
                    conn.execute(
                        "INSERT INTO workflows (id, data) VALUES (?, ?)",
                        (w["id"], json.dumps(w, ensure_ascii=False)),
                    )
            conn.commit()
    except Exception as exc:
        print(f"[ERROR] 保存工作流失败：{exc}", flush=True)


# -------------------------------------------------------------
# 对话会话（Session）
# -------------------------------------------------------------
def create_session(meta: dict) -> bool:
    """创建会话记录。meta: id/title/workspace_id/model_preset_id/skill_ids/knowledge_ids/memory_enabled/created_at/updated_at"""
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (id, title, workspace_id, model_preset_id, skill_ids, knowledge_ids,
                    memory_enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta.get("id", ""),
                    meta.get("title", "新对话"),
                    meta.get("workspace_id") or None,
                    meta.get("model_preset_id") or None,
                    json.dumps(meta.get("skill_ids") or [], ensure_ascii=False),
                    json.dumps(meta.get("knowledge_ids") or [], ensure_ascii=False),
                    1 if meta.get("memory_enabled", True) else 0,
                    meta.get("created_at", 0.0),
                    meta.get("updated_at", 0.0),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        print(f"[ERROR] 创建会话失败：{exc}", flush=True)
        return False


def load_session(session_id: str) -> dict | None:
    """加载会话（含消息）。返回 {meta..., messages: [...]} 或 None。"""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None
            s = _row_to_dict(row)
            s["skill_ids"] = _safe_json_list(s.get("skill_ids"))
            s["knowledge_ids"] = _safe_json_list(s.get("knowledge_ids"))
            s["memory_enabled"] = bool(s.get("memory_enabled", 1))

            rows = conn.execute(
                "SELECT role, content, tool_call_id, tool_calls FROM session_messages WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()
            messages = []
            for r in rows:
                msg = {"role": r["role"], "content": _safe_json(r["content"])}
                if r["tool_call_id"]:
                    msg["tool_call_id"] = r["tool_call_id"]
                if r["tool_calls"]:
                    msg["tool_calls"] = _safe_json(r["tool_calls"])
                messages.append(msg)
            s["messages"] = messages
            return s
    except Exception as exc:
        print(f"[ERROR] 加载会话失败：{exc}", flush=True)
        return None


def list_sessions(limit: int = 100, workspace_id: str | None = None) -> list[dict]:
    """列出会话摘要（不含消息），按最近活跃排序。"""
    try:
        with _get_conn() as conn:
            sql = """
                SELECT s.id, s.title, s.workspace_id, s.model_preset_id, s.memory_enabled,
                       s.created_at, s.updated_at,
                       (SELECT COUNT(*) FROM session_messages m WHERE m.session_id = s.id) AS message_count
                FROM sessions s
            """
            params: list = []
            if workspace_id:
                sql += " WHERE s.workspace_id = ?"
                params.append(workspace_id)
            sql += " ORDER BY s.updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                item = _row_to_dict(r)
                item["memory_enabled"] = bool(item.get("memory_enabled", 1))
                item["title"] = item.get("title") or "新对话"
                out.append(item)
            return out
    except Exception as exc:
        print(f"[ERROR] 列出会话失败：{exc}", flush=True)
        return []


def update_session_meta(session_id: str, **fields) -> bool:
    """更新会话元数据字段。fields 为 {title/workspace_id/model_preset_id/skill_ids/knowledge_ids/memory_enabled/updated_at}。"""
    try:
        allowed = {
            "title", "workspace_id", "model_preset_id", "skill_ids",
            "knowledge_ids", "memory_enabled", "updated_at",
        }
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("skill_ids", "knowledge_ids"):
                v = json.dumps(v or [], ensure_ascii=False)
            elif k == "memory_enabled":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            params.append(v)
        if not sets:
            return False
        params.append(session_id)
        with _get_conn() as conn:
            conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)
            conn.commit()
        return True
    except Exception as exc:
        print(f"[ERROR] 更新会话失败：{exc}", flush=True)
        return False


def append_session_messages(session_id: str, messages: list[dict]) -> bool:
    """追加消息到会话，seq 自动递增。"""
    if not messages:
        return True
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM session_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["next_seq"]) if row else 0
            for msg in messages:
                role = msg.get("role", "")
                content = json.dumps(msg.get("content", ""), ensure_ascii=False)
                tool_call_id = msg.get("tool_call_id")
                tool_calls = json.dumps(msg.get("tool_calls"), ensure_ascii=False) if msg.get("tool_calls") else None
                conn.execute(
                    """INSERT INTO session_messages (session_id, seq, role, content, tool_call_id, tool_calls)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, seq, role, content, tool_call_id, tool_calls),
                )
                seq += 1
            conn.commit()
        # 同步全文索引（Hermes D4；表缺失/异常时静默跳过）
        try:
            _reindex_session_fts(session_id)
        except Exception:
            pass
        return True
    except Exception as exc:
        print(f"[ERROR] 追加会话消息失败：{exc}", flush=True)
        return False


def replace_session_messages(session_id: str, messages: list[dict]) -> bool:
    """整体替换会话消息（上下文压缩后使用）：删除全部后重插，seq 从 0 开始。"""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            seq = 0
            for msg in messages:
                role = msg.get("role", "")
                content = json.dumps(msg.get("content", ""), ensure_ascii=False)
                tool_call_id = msg.get("tool_call_id")
                tool_calls = json.dumps(msg.get("tool_calls"), ensure_ascii=False) if msg.get("tool_calls") else None
                conn.execute(
                    """INSERT INTO session_messages (session_id, seq, role, content, tool_call_id, tool_calls)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, seq, role, content, tool_call_id, tool_calls),
                )
                seq += 1
            conn.commit()
        # 压缩后重建该会话全文索引（Hermes D4）
        try:
            _reindex_session_fts(session_id)
        except Exception:
            pass
        return True
    except Exception as exc:
        print(f"[ERROR] 替换会话消息失败：{exc}", flush=True)
        return False


def _reindex_session_fts(session_id: str) -> bool:
    """重建单个会话的 FTS5 索引（删除旧行后从 session_messages 全量重插）。"""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM session_fts WHERE session_id = ?", (session_id,))
            rows = conn.execute(
                "SELECT role, content FROM session_messages WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()
            for r in rows:
                conn.execute(
                    "INSERT INTO session_fts (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, r["role"], r["content"]),
                )
            conn.commit()
        return True
    except Exception:
        return False


def delete_session(session_id: str) -> bool:
    """删除会话及其全部消息。"""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_fts WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
        return True
    except Exception as exc:
        print(f"[ERROR] 删除会话失败：{exc}", flush=True)
        return False


# -------------------------------------------------------------
# 会话全文检索（FTS5 + LIKE 兜底）
# -------------------------------------------------------------
def _msg_content_to_text(raw) -> str:
    """把 session_messages.content（JSON 编码存储）还原为纯文本，供 FTS 索引与摘要展示。"""
    if not raw:
        return ""
    decoded = _safe_json(raw)
    if isinstance(decoded, str):
        return decoded
    if isinstance(decoded, list):  # 多模态/多段内容：拼 text 段
        parts = []
        for p in decoded:
            if isinstance(p, dict):
                parts.append(p.get("text") or "")
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    return str(raw)


def rebuild_session_fts() -> bool:
    """遍历 session_messages 全量重建 FTS 索引。失败（如无 FTS5 支持）返回 False，不抛出。"""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM session_fts")
            rows = conn.execute(
                "SELECT session_id, role, content FROM session_messages"
            ).fetchall()
            conn.executemany(
                "INSERT INTO session_fts (session_id, role, content) VALUES (?, ?, ?)",
                [
                    (r["session_id"], r["role"] or "", _msg_content_to_text(r["content"]))
                    for r in rows
                ],
            )
            conn.commit()
        return True
    except Exception as exc:
        print(f"[ERROR] 重建会话全文索引失败：{exc}", flush=True)
        return False


def _make_snippet(text: str, q: str, width: int = 60) -> str:
    """截取命中词前后约 width 字符作为摘要片段，片段两端补省略号。"""
    text = (text or "").strip()
    if not text:
        return ""
    term = q or ""
    idx = text.find(term) if term else -1
    if idx < 0 and term:  # FTS 分词后整句可能不连续，退而定位首个词
        tokens = [t for t in term.split() if t]
        if tokens:
            t0 = tokens[0]
            idx = text.find(t0)
            if idx >= 0:
                term = t0
    if idx < 0:
        start, end = 0, min(len(text), width * 2)
    else:
        start = max(0, idx - width)
        end = min(len(text), idx + len(term) + width)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def search_sessions(q: str, limit: int = 20) -> list[dict]:
    """跨会话全文检索。

    返回 [{session_id, title, snippet, updated_at}]，按会话最近活跃时间倒序，每会话最多一条。
    - FTS5 可用：查询词整体加引号做 MATCH（含特殊字符时容错）；
    - FTS5 不可用 / MATCH 报错 / 无命中：自动降级为 LIKE '%q%' 兜底，绝不抛出。
    """
    if not q or not str(q).strip():
        return []
    q = str(q).strip()

    def _like_rows(cur):
        # LIKE 兜底：对原始存储文本做子串匹配，转义 %/_ 通配符
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql = (
            "SELECT m.session_id, m.content AS raw_content, s.title, s.updated_at "
            "FROM session_messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE m.content LIKE ? ESCAPE '\\' ORDER BY s.updated_at DESC"
        )
        return cur.execute(sql, (f"%{esc}%",)).fetchall()

    try:
        with _get_conn() as conn:
            rows = []
            try:
                # 整体转成引号短语：内部双引号翻倍转义，避免 MATCH 语法错误
                phrase = '"' + q.replace('"', '""') + '"'
                rows = conn.execute(
                    "SELECT f.session_id, f.content AS raw_content, s.title, s.updated_at "
                    "FROM session_fts f JOIN sessions s ON s.id = f.session_id "
                    "WHERE session_fts MATCH ? ORDER BY s.updated_at DESC",
                    (phrase,),
                ).fetchall()
            except Exception:
                rows = []  # FTS 表缺失/无 FTS5 支持/MATCH 语法错误 → 走 LIKE
            if not rows:
                rows = _like_rows(conn)
            # 同会话多条消息命中时只取一条（会话级结果），不设 SQL LIMIT 以保证去重后条数准确
            seen, out = set(), []
            for r in rows:
                sid = r["session_id"]
                if sid in seen:
                    continue
                seen.add(sid)
                out.append({
                    "session_id": sid,
                    "title": r["title"] or "新对话",
                    "snippet": _make_snippet(_msg_content_to_text(r["raw_content"]), q),
                    "updated_at": r["updated_at"],
                })
                if len(out) >= limit:
                    break
            return out
    except Exception as exc:
        print(f"[ERROR] 会话全文检索失败：{exc}", flush=True)
        return []


def _safe_json(data) -> Any:
    """尝试解析 JSON，失败原样返回。"""
    if data is None:
        return None
    try:
        return json.loads(data)
    except Exception:
        return data


def _safe_json_list(data) -> list:
    val = _safe_json(data)
    return val if isinstance(val, list) else []
