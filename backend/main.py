#!/usr/bin/env python
"""CrewAI 工作台 - 后端服务
FastAPI 封装 crewAI：提供任务运行 API + 日志查询 API + 静态前端页面服务。
启动方式：
  python backend/main.py          # 开发模式（默认 8000 端口，自动打开浏览器）
  打包后双击 exe                   # 自动打开浏览器，.env 放在 exe 同目录
"""
import contextvars
import io
import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from collections import deque
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------
# 路径规划：
#   - 开发模式：资源根目录 = 项目根目录（backend/..）
#   - 打包模式：资源根目录 = sys._MEIPASS（PyInstaller 解压目录）
#   - .env 优先从 exe 所在目录读取（用户把 .env 放 exe 旁边）
# ---------------------------------------------------------------
PACKAGED = hasattr(sys, "_MEIPASS")
if PACKAGED:
    BASE_DIR = Path(sys._MEIPASS)  # 打包后资源（含 frontend/）所在目录
    EXE_DIR = Path(sys.executable).parent  # exe 所在目录（放 .env 用）
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    EXE_DIR = BASE_DIR

load_dotenv(EXE_DIR / ".env")  # 先读 exe 同目录 .env
if not os.getenv("DEEPSEEK_API_KEY") and not PACKAGED:
    load_dotenv(BASE_DIR / ".env")  # 开发模式兜底再读项目根 .env

from crewai import Agent, Crew, LLM, Process, Task  # noqa: E402

app = FastAPI(title="CrewAI Workbench", version="1.2.0")

# ---------------------------------------------------------------
# 模型配置（用户点击前端头像配置，持久化到 model_config.json）
#   开发模式: 项目根目录/model_config.json
#   打包模式: exe 同目录/model_config.json
# ---------------------------------------------------------------
MODEL_CONFIG_FILE = EXE_DIR / "model_config.json"
WORKSPACES_FILE = EXE_DIR / "workspaces.json"

DEFAULT_MODEL_CONFIG: dict[str, str] = {
    "provider": "deepseek",
    "model": "deepseek/deepseek-chat",
    "api_key": "",
    "base_url": "https://api.deepseek.com",
}


def _load_model_config() -> dict[str, str]:
    """读取模型配置，文件不存在时返回默认（DeepSeek）。"""
    cfg = dict(DEFAULT_MODEL_CONFIG)
    try:
        if MODEL_CONFIG_FILE.exists():
            with open(MODEL_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULT_MODEL_CONFIG:
                    if isinstance(data.get(k), str):
                        cfg[k] = data[k].strip()
    except Exception:
        pass
    return cfg


def _save_model_config(cfg: dict[str, str]) -> None:
    """保存模型配置到本地 JSON 文件。"""
    try:
        with open(MODEL_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        log_buffer.emit("ERROR", "system", f"保存模型配置失败：{exc}")


# ---------------------------------------------------------------
# 工作空间管理
#   开发模式: 项目根目录/workspaces.json
#   打包模式: exe 同目录/workspaces.json
# ---------------------------------------------------------------
DEFAULT_WORKSPACE_ID: str | None = None


def _load_workspaces() -> dict:
    """读取工作空间配置（含列表与当前选中项）。"""
    default = {"current_id": None, "workspaces": []}
    try:
        if WORKSPACES_FILE.exists():
            with open(WORKSPACES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if isinstance(data.get("workspaces"), list):
                    default["workspaces"] = data["workspaces"]
                if isinstance(data.get("current_id"), str):
                    default["current_id"] = data["current_id"]
    except Exception:
        pass
    return default


def _save_workspaces(data: dict) -> None:
    """保存工作空间配置到本地 JSON 文件。"""
    try:
        with open(WORKSPACES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        log_buffer.emit("ERROR", "system", f"保存工作空间失败：{exc}")


def _normalize_workspace_path(path: str) -> str:
    """统一工作空间路径格式,并校验目录是否存在。"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"目录不存在：{path}")
    if not p.is_dir():
        raise ValueError(f"路径不是目录：{path}")
    return str(p)


def _list_workspace_files(path: str, max_depth: int = 3) -> list[dict]:
    """安全地列出工作空间目录下的文件（限制深度、跳过隐藏目录、限制数量）。"""
    root = Path(path).resolve()
    files = []
    count = 0
    max_files = 500

    def _scan(dir_path: Path, depth: int):
        nonlocal count
        if depth > max_depth or count >= max_files:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                rel = entry.relative_to(root)
            except ValueError:
                continue
            is_dir = entry.is_dir()
            item = {
                "name": entry.name,
                "path": str(entry),
                "rel": str(rel).replace("\\", "/"),
                "is_dir": is_dir,
                "size": entry.stat().st_size if entry.is_file() else 0,
            }
            files.append(item)
            count += 1
            if is_dir:
                _scan(entry, depth + 1)

    _scan(root, 1)
    return files


def _get_current_workspace() -> dict | None:
    """获取当前选中的工作空间。"""
    data = _load_workspaces()
    current_id = data.get("current_id")
    for ws in data.get("workspaces", []):
        if ws.get("id") == current_id:
            return ws
    # 如果没有当前项但有工作空间,默认选第一个
    if data.get("workspaces"):
        first = data["workspaces"][0]
        data["current_id"] = first["id"]
        _save_workspaces(data)
        return first
    return None


def _build_llm() -> LLM:
    """根据用户配置动态构建 LLM（兼容 provider/model 与裸 model 格式）。"""
    cfg = _load_model_config()
    model = cfg.get("model") or DEFAULT_MODEL_CONFIG["model"]
    api_key = cfg.get("api_key") or os.getenv("DEEPSEEK_API_KEY", "")
    base_url = (cfg.get("base_url") or "").strip() or None
    kwargs: dict[str, Any] = {"model": model}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    return LLM(**kwargs)

# ---------------------------------------------------------------
# 日志采集系统
# ---------------------------------------------------------------
LOG_MAX_MEMORY = 3000  # 内存中保留最近日志条数
_current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)


class _LogRecord(BaseModel):
    id: str
    time: str  # ISO-8601 with timezone
    task_id: str | None
    level: str
    source: str  # agent / system / stdout / stderr
    message: str


class _LogBuffer:
    """线程安全的内存日志缓冲，同时写入滚动文件。"""

    def __init__(self, max_size: int = LOG_MAX_MEMORY) -> None:
        self._records: deque[_LogRecord] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._file_path: Path | None = None
        if not PACKAGED:
            log_dir = BASE_DIR / "logs"
            log_dir.mkdir(exist_ok=True)
            self._file_path = log_dir / "app.log"

    def emit(self, level: str, source: str, message: str, task_id: str | None = None) -> _LogRecord:
        record = _LogRecord(
            id=uuid.uuid4().hex[:12],
            time=datetime.now(timezone.utc).astimezone().isoformat(),
            task_id=task_id or _current_task_id.get(),
            level=level.upper(),
            source=source,
            message=message,
        )
        with self._lock:
            self._records.append(record)
        if self._file_path:
            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(f"[{record.time}] [{record.level}] [{record.source}] {record.task_id or '-'} {record.message}\n")
            except Exception:
                pass
        return record

    def query(
        self,
        task_id: str | None = None,
        level: str | None = None,
        keyword: str | None = None,
        start: str | None = None,
        end: str | None = None,
        source: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[list[_LogRecord], int]:
        level_set = {lvl.strip().upper() for lvl in (level or "").split(",") if lvl.strip()} if level else set()
        start_dt = _parse_iso(start) if start else None
        end_dt = _parse_iso(end) if end else None
        all_matched: list[_LogRecord] = []
        with self._lock:
            for rec in self._records:
                if task_id and rec.task_id != task_id:
                    continue
                if level_set and rec.level not in level_set:
                    continue
                if source and rec.source != source:
                    continue
                if keyword and keyword.lower() not in rec.message.lower():
                    continue
                rec_dt = _parse_iso(rec.time)
                if start_dt and rec_dt and rec_dt < start_dt:
                    continue
                if end_dt and rec_dt and rec_dt > end_dt:
                    continue
                all_matched.append(rec)
        # 倒序返回：最近优先
        all_matched.reverse()
        total = len(all_matched)
        return all_matched[offset : offset + limit], total

    def task_ids(self) -> list[str]:
        ids: set[str] = set()
        with self._lock:
            for rec in self._records:
                if rec.task_id:
                    ids.add(rec.task_id)
        return sorted(ids, reverse=True)


log_buffer = _LogBuffer()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # 处理带时区 2026-08-14T13:00:00+08:00 或 2026-08-14T13:00:00
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class _MemoryLogHandler(logging.Handler):
    """把 Python logging 的日志转发到内存缓冲。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            source = "system"
            # 尝试识别 crewai 的 Agent 日志
            agent_match = re.search(r"Agent:\s*(\S+.*?)(?:\s*[|]\s*|\s+|$)", msg)
            if agent_match:
                source = agent_match.group(1).strip()[:40]
            elif "crewai" in record.name.lower():
                source = "crewai"
            log_buffer.emit(record.levelname, source, msg)
        except Exception:
            self.handleError(record)


# 配置根 logger，让 crewai / uvicorn / 其他库的日志都进入内存
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)
# 避免重复添加 handler（模块重载时）
if not any(isinstance(h, _MemoryLogHandler) for h in _root_logger.handlers):
    _mem_handler = _MemoryLogHandler()
    _mem_handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
    _root_logger.addHandler(_mem_handler)

# 捕获 uvicorn 访问日志也进入内存
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@contextmanager
def _capture_stdio(task_id: str):
    """在线程内捕获 stdout/stderr 作为该 task 的日志。"""
    token = _current_task_id.set(task_id)
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    class _Tee:
        def __init__(self, original, buffer, level):
            self._original = original
            self._buffer = buffer
            self._level = level
            self._source = "stdout" if level == "INFO" else "stderr"
            self._task_id = task_id

        def write(self, data: str) -> int:
            self._buffer.write(data)
            # 同时写入原终端，方便调试
            try:
                self._original.write(data)
                self._original.flush()
            except Exception:
                pass
            # 按行缓冲写入日志
            for line in data.splitlines():
                line = line.strip()
                if line:
                    log_buffer.emit(self._level, self._source, line, self._task_id)
            return len(data)

        def flush(self) -> None:
            try:
                self._original.flush()
            except Exception:
                pass

        def isatty(self) -> bool:
            return False

    tee_out = _Tee(original_stdout, stdout_capture, "INFO")
    tee_err = _Tee(original_stderr, stderr_capture, "ERROR")
    sys.stdout = tee_out
    sys.stderr = tee_err
    try:
        yield
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        _current_task_id.reset(token)


# ---------------------------------------------------------------
# 任务管理
# ---------------------------------------------------------------
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _read_workspace_context(workspace_path: str | None, max_chars: int = 30000) -> str:
    """读取工作空间内文本文件内容,作为任务上下文。"""
    if not workspace_path:
        return ""
    root = Path(workspace_path).resolve()
    if not root.exists() or not root.is_dir():
        return ""
    text_exts = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log"}
    collected: list[str] = []
    total = 0
    try:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in text_exts:
                continue
            try:
                # 限制单文件读取大小
                size = path.stat().st_size
                if size > 200_000:
                    snippet = f"[文件过大,仅显示路径] {path.relative_to(root).as_posix()}\n"
                    collected.append(snippet)
                    total += len(snippet)
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                header = f"\n--- 文件: {path.relative_to(root).as_posix()} ---\n"
                piece = header + content
                if total + len(piece) > max_chars:
                    remaining = max_chars - total - len(header) - 50
                    if remaining > 200:
                        piece = header + content[:remaining] + "\n...[截断]\n"
                    else:
                        collected.append("\n...[更多文件内容已省略]\n")
                        break
                collected.append(piece)
                total += len(piece)
            except Exception:
                continue
    except Exception:
        pass
    if not collected:
        return ""
    return "以下是与主题相关的本地项目文件内容,请结合这些材料进行调研与分析：\n" + "".join(collected)


def _build_crew(topic: str, workspace_path: str | None = None) -> Crew:
    """构建固定双 Agent 协作 Crew（研究员 + 分析师），LLM 由用户配置决定。"""
    llm = _build_llm()
    context = _read_workspace_context(workspace_path)
    researcher = Agent(
        role="资深研究员",
        goal="调研 {topic} 的最新进展，找出最有价值的信息",
        backstory="你是一位经验丰富的研究员，擅长收集、筛选和分析信息，总能找到最关键的内容。",
        llm=llm,
        verbose=True,
    )
    writer = Agent(
        role="写作分析师",
        goal="基于研究内容撰写一份简洁、清晰的报告",
        backstory="你是一位出色的分析师，擅长把复杂的信息整理成条理清晰、易于理解的报告。",
        llm=llm,
        verbose=True,
    )
    research_task = Task(
        description="对主题「{topic}」进行调研，找出最相关、最新颖的信息，包括核心概念、最新进展和代表性应用。" + ("\n\n可参考的本地项目上下文:\n{context}" if context else ""),
        expected_output="5 条关于 {topic} 的关键要点，每条包含具体说明。",
        agent=researcher,
    )
    write_task = Task(
        description="基于研究员提供的要点，撰写一份 markdown 格式的简要报告，结构清晰、重点突出。",
        expected_output="一份 markdown 格式的 {topic} 简要报告。",
        agent=writer,
    )
    return Crew(
        agents=[researcher, writer],
        tasks=[research_task, write_task],
        process=Process.sequential,
        verbose=True,
    ), context


def _workspace_path_by_id(workspace_id: str | None) -> str | None:
    """根据 workspace_id 获取路径。"""
    if not workspace_id:
        return None
    data = _load_workspaces()
    for ws in data.get("workspaces", []):
        if ws.get("id") == workspace_id:
            return ws.get("path")
    return None


def _run_crew_async(task_id: str, topic: str, workspace_id: str | None = None):
    """后台线程执行 crew，并采集详细日志。"""
    try:
        ws_path = _workspace_path_by_id(workspace_id)
        with _tasks_lock:
            _tasks[task_id]["status"] = "running"
        log_buffer.emit("INFO", "system", f"任务 {task_id} 开始执行，主题：{topic}", task_id)
        if ws_path:
            log_buffer.emit("INFO", "system", f"已关联工作空间：{ws_path}", task_id)
        with _capture_stdio(task_id):
            crew, context = _build_crew(topic, workspace_path=ws_path)
            log_buffer.emit("INFO", "system", "Crew 已构建，Agent：资深研究员 → 写作分析师", task_id)
            inputs: dict[str, Any] = {"topic": topic}
            if context:
                inputs["context"] = context
                log_buffer.emit("INFO", "system", f"已注入工作空间上下文（{len(context)} 字符）", task_id)
            result = crew.kickoff(inputs=inputs)
            log_buffer.emit("INFO", "system", "Crew 执行完成", task_id)
        with _tasks_lock:
            _tasks[task_id].update(status="completed", result=str(result))
        log_buffer.emit("INFO", "system", f"任务 {task_id} 已完成", task_id)
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        log_buffer.emit("ERROR", "system", f"任务 {task_id} 执行失败：{err_msg}", task_id)
        with _tasks_lock:
            _tasks[task_id].update(status="failed", error=err_msg)


# ---------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------
class RunRequest(BaseModel):
    topic: str
    workspace_id: str = ""


@app.get("/api/health")
def health():
    cfg = _load_model_config()
    key_ok = bool(cfg.get("api_key")) or bool(os.getenv("DEEPSEEK_API_KEY"))
    current_ws = _get_current_workspace()
    return {
        "status": "ok",
        "api_key_configured": key_ok,
        "provider": cfg.get("provider", ""),
        "model": cfg.get("model", ""),
        "workspace": {
            "id": current_ws.get("id") if current_ws else None,
            "name": current_ws.get("name") if current_ws else None,
            "path": current_ws.get("path") if current_ws else None,
        },
    }


class ModelConfigRequest(BaseModel):
    provider: str = "deepseek"
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@app.get("/api/config")
def get_model_config():
    """返回当前模型配置（API Key 脱敏，仅返回是否已配置）。"""
    cfg = _load_model_config()
    masked = dict(cfg)
    masked["has_api_key"] = bool(cfg.get("api_key")) or bool(os.getenv("DEEPSEEK_API_KEY"))
    masked["api_key"] = ""
    return masked


@app.post("/api/config")
def set_model_config(req: ModelConfigRequest):
    """保存模型配置。api_key 留空则保留原 Key（避免误清空）。"""
    old = _load_model_config()
    api_key = req.api_key.strip()
    if not api_key:
        api_key = old.get("api_key", "")
    cfg = {
        "provider": req.provider.strip() or old.get("provider", "deepseek"),
        "model": req.model.strip() or old.get("model", ""),
        "api_key": api_key,
        "base_url": req.base_url.strip(),
    }
    _save_model_config(cfg)
    log_buffer.emit(
        "INFO", "system",
        f"模型配置已更新：{cfg['provider']} / {cfg['model'] or '(未填)'} / API Key {'已设置' if cfg['api_key'] else '未设置'}",
    )
    return {"ok": True, "has_api_key": bool(cfg["api_key"])}


@app.post("/api/run")
def run_task(req: RunRequest):
    topic = req.topic.strip()
    if not topic:
        return JSONResponse({"error": "主题不能为空"}, status_code=400)
    workspace_id = (req.workspace_id or "").strip()
    # 未指定时回退到当前工作空间
    if not workspace_id:
        current_ws = _get_current_workspace()
        workspace_id = current_ws.get("id") if current_ws else ""
    task_id = uuid.uuid4().hex[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "topic": topic,
            "status": "queued",
            "workspace_id": workspace_id,
            "result": None,
            "error": None,
        }
    log_buffer.emit("INFO", "system", f"收到新任务：{topic}", task_id)
    thread = threading.Thread(target=_run_crew_async, args=(task_id, topic, workspace_id or None), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.get("/api/status/{task_id}")
def task_status(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return task


@app.get("/api/tasks")
def list_tasks(workspace_id: str | None = Query(None)):
    # 倒序返回,最多 50 个;可按 workspace_id 过滤
    tasks = sorted(_tasks.values(), key=lambda t: t["id"], reverse=True)
    if workspace_id:
        tasks = [t for t in tasks if t.get("workspace_id") == workspace_id]
    return {"tasks": tasks[:50]}


@app.get("/api/logs")
def query_logs(
    task_id: str | None = Query(None),
    level: str | None = Query(None),
    keyword: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    records, total = log_buffer.query(
        task_id=task_id,
        level=level,
        keyword=keyword,
        start=start,
        end=end,
        source=source,
        limit=limit,
        offset=offset,
    )
    return {"logs": [rec.model_dump() for rec in records], "total": total}


@app.get("/api/log-tasks")
def log_task_ids():
    """返回有日志记录的任务 ID 列表（用于前端下拉筛选）。"""
    ids = log_buffer.task_ids()
    # 补充当前任务字典中的 topic
    infos = []
    for tid in ids:
        t = _tasks.get(tid)
        infos.append({"id": tid, "topic": t["topic"] if t else None})
    return {"tasks": infos}


@app.get("/api/log-stream")
def log_stream(task_id: str | None = Query(None)):
    """SSE 实时日志流（可选，前端可用也可轮询）。"""

    async def _event_generator():
        last_count = len(log_buffer._records)
        while True:
            await __import__("asyncio").sleep(1)
            current_records = list(log_buffer._records)
            if len(current_records) > last_count:
                new_records = current_records[last_count:]
                last_count = len(current_records)
                for rec in new_records:
                    if task_id and rec.task_id != task_id:
                        continue
                    data = rec.model_dump_json()
                    yield f"data: {data}\n\n"

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------
# 工作空间 API
# ---------------------------------------------------------------
class WorkspaceCreateRequest(BaseModel):
    name: str
    path: str


@app.get("/api/workspaces")
def list_workspaces():
    """列出所有工作空间与当前选中项。"""
    data = _load_workspaces()
    return {
        "current_id": data.get("current_id"),
        "workspaces": data.get("workspaces", []),
    }


@app.post("/api/workspaces")
def create_workspace(req: WorkspaceCreateRequest):
    """创建并切换到一个新工作空间。"""
    name = req.name.strip()
    path = req.path.strip()
    if not name:
        return JSONResponse({"error": "工作空间名称不能为空"}, status_code=400)
    if not path:
        return JSONResponse({"error": "工作空间路径不能为空"}, status_code=400)
    try:
        normalized = _normalize_workspace_path(path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    data = _load_workspaces()
    ws_id = uuid.uuid4().hex[:12]
    workspace = {
        "id": ws_id,
        "name": name,
        "path": normalized,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    data["workspaces"].append(workspace)
    data["current_id"] = ws_id
    _save_workspaces(data)
    log_buffer.emit("INFO", "system", f"创建工作空间：{name} → {normalized}")
    return {"workspace": workspace, "current_id": ws_id}


@app.get("/api/workspaces/{workspace_id}")
def get_workspace(workspace_id: str):
    data = _load_workspaces()
    for ws in data.get("workspaces", []):
        if ws.get("id") == workspace_id:
            return ws
    return JSONResponse({"error": "工作空间不存在"}, status_code=404)


@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    data = _load_workspaces()
    before = len(data.get("workspaces", []))
    data["workspaces"] = [ws for ws in data.get("workspaces", []) if ws.get("id") != workspace_id]
    if len(data["workspaces"]) == before:
        return JSONResponse({"error": "工作空间不存在"}, status_code=404)
    if data.get("current_id") == workspace_id:
        data["current_id"] = data["workspaces"][0]["id"] if data["workspaces"] else None
    _save_workspaces(data)
    log_buffer.emit("INFO", "system", f"删除工作空间：{workspace_id}")
    return {"ok": True, "current_id": data.get("current_id")}


@app.post("/api/workspaces/{workspace_id}/switch")
def switch_workspace(workspace_id: str):
    data = _load_workspaces()
    exists = any(ws.get("id") == workspace_id for ws in data.get("workspaces", []))
    if not exists:
        return JSONResponse({"error": "工作空间不存在"}, status_code=404)
    data["current_id"] = workspace_id
    _save_workspaces(data)
    ws = next((w for w in data["workspaces"] if w["id"] == workspace_id), {})
    log_buffer.emit("INFO", "system", f"切换工作空间：{ws.get('name')} → {ws.get('path')}")
    return {"current_id": workspace_id, "workspace": ws}


@app.get("/api/workspaces/{workspace_id}/files")
def list_workspace_files_api(workspace_id: str, max_depth: int = Query(3, ge=1, le=5)):
    data = _load_workspaces()
    ws = next((w for w in data.get("workspaces", []) if w.get("id") == workspace_id), None)
    if not ws:
        return JSONResponse({"error": "工作空间不存在"}, status_code=404)
    path = ws.get("path")
    if not path or not Path(path).exists():
        return JSONResponse({"error": "工作空间目录不存在"}, status_code=400)
    try:
        files = _list_workspace_files(path, max_depth=max_depth)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"读取目录失败：{exc}"}, status_code=500)
    return {"files": files}


@app.get("/api/browse-directory")
def browse_directory():
    """弹出系统目录选择对话框，返回用户选择的目录路径。

    使用 Windows 原生的 FolderBrowserDialog（PowerShell），置顶显示。
    注意：该接口会阻塞等待用户在弹窗中完成选择；取消或超时返回 canceled=True。
    服务进程必须能访问桌面会话（非沙箱），否则 GUI 弹窗无法显示。
    """
    try:
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "[System.Windows.Forms.Application]::EnableVisualStyles(); "
            "$form = New-Object System.Windows.Forms.Form; "
            "$form.TopMost = $true; "
            "$form.ShowInTaskbar = $false; "
            "$form.WindowState = 'Minimized'; "
            "$form.CreateControl(); "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = '选择工作目录'; "
            "$f.ShowNewFolderButton = $true; "
            "$r = $f.ShowDialog($form); "
            "$form.Close(); "
            "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { $f.SelectedPath } else { '' }"
        )
        result = subprocess.run(
            ["powershell.exe", "-Sta", "-WindowStyle", "Hidden", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            check=False,
        )
        path = (result.stdout or "").strip()
        if not path:
            return {"canceled": True, "path": ""}
        normalized = _normalize_workspace_path(path)
        return {"canceled": False, "path": normalized}
    except subprocess.TimeoutExpired:
        return {"canceled": True, "path": ""}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"打开目录选择对话框失败：{exc}"}, status_code=500)


class WorkspaceFileItem(BaseModel):
    path: str
    content: str


class WorkspaceUploadRequest(BaseModel):
    files: list[WorkspaceFileItem]
    directory_name: str = ""


@app.post("/api/workspaces/upload")
def upload_workspace_files(req: WorkspaceUploadRequest):
    """接收前端上传的目录文件，保存到临时目录，返回绝对路径供创建工作空间使用。"""
    files = req.files or []
    if not files:
        return JSONResponse({"error": "没有可上传的文件"}, status_code=400)

    try:
        # 开发模式放在项目根目录下的 temp_workspaces；打包模式放在 exe 同目录
        temp_root = EXE_DIR / "temp_workspaces"
        temp_root.mkdir(exist_ok=True)
        # 按 directory_name + uuid 创建子目录，避免冲突
        slug = re.sub(r"[^\w\-]", "_", req.directory_name.strip() or "workspace")[:32]
        temp_dir = temp_root / f"{slug}_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        for item in files:
            rel = item.path.strip().lstrip("/\\")
            if not rel or ".." in Path(rel).parts:
                continue
            target = (temp_dir / rel).resolve()
            if not str(target).startswith(str(temp_dir.resolve())):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fp:
                fp.write(item.content)
            written += 1

        log_buffer.emit("INFO", "system", f"上传工作空间文件到临时目录：{temp_dir}（{written} 个文件）")
        return {"path": _normalize_workspace_path(str(temp_dir)), "file_count": written}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"上传文件失败：{exc}"}, status_code=500)


# ---------------------------------------------------------------
# 静态页面（前端）
# ---------------------------------------------------------------
FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


if PACKAGED:
    # 打包后静态文件嵌入在 _MEIPASS/frontend
    app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")
else:
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ---------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------
def main():
    import socket
    import webbrowser

    port = int(os.getenv("CREWAI_APP_PORT", "8000"))

    # 检查端口占用，被占用则自动 +1
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break
            port += 1

    url = f"http://127.0.0.1:{port}"
    print("=" * 56)
    print("  CrewAI Workbench 已启动")
    print(f"  访问地址: {url}")
    print(f"  API Key  : {'已配置' if os.getenv('DEEPSEEK_API_KEY') else '未配置（请在 .env 中填写）'}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
