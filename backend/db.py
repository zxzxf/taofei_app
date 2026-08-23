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
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_ws ON memory_entries(workspace_id)")

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
