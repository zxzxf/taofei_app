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
import platform
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

# 注意：部分 crewai 版本（或安装方式）的顶级导出中不再包含独立的 LLM 类，
# 也没有 crewai.llms 子模块；因此将核心类（Agent/Crew/Process/Task）与 LLM
# 包装类分开导入：只要核心类存在即认为 HAS_CREWAI=True，LLM 缺失时由下方
# _LLMCompat 适配器基于 langchain_openai 提供等效能力。
try:
    from crewai import Agent, Crew, Process, Task  # noqa: E402
    HAS_CREWAI = True
except ImportError:
    HAS_CREWAI = False
    Agent = Crew = Process = Task = None  # type: ignore

try:
    from crewai import LLM  # noqa: E402,F811
except ImportError:
    LLM = None  # type: ignore

app = FastAPI(title="CrewAI Workbench", version="1.2.0")

# ---------------------------------------------------------------
# 模型配置（用户点击前端头像配置，持久化到 model_config.json）
#   开发模式: 项目根目录/model_config.json
#   打包模式: exe 同目录/model_config.json
# ---------------------------------------------------------------
MODEL_CONFIG_FILE = EXE_DIR / "model_config.json"
WORKSPACES_FILE = EXE_DIR / "workspaces.json"
MODEL_PRESETS_FILE = EXE_DIR / "model_presets.json"

DEFAULT_MODEL_CONFIG: dict[str, str] = {
    "provider": "deepseek",
    "model": "deepseek-chat",
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
# 模型预设（多套配置，可命名保存、切换、删除）
#   持久化到 model_presets.json
#   结构：{"presets": [...], "active_id": "..."}
# ---------------------------------------------------------------
def _load_presets() -> dict:
    """读取模型预设列表。"""
    default: dict = {"presets": [], "active_id": ""}
    try:
        if MODEL_PRESETS_FILE.exists():
            with open(MODEL_PRESETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if isinstance(data.get("presets"), list):
                    default["presets"] = data["presets"]
                if isinstance(data.get("active_id"), str):
                    default["active_id"] = data["active_id"]
    except Exception:
        pass
    return default


def _save_presets(data: dict) -> None:
    """保存模型预设到本地 JSON 文件。"""
    try:
        with open(MODEL_PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        log_buffer.emit("ERROR", "system", f"保存模型预设失败：{exc}")


def _mask_api_key(key: str) -> str:
    """脱敏 API Key：保留前 4 后 4，中间 * 号。空或太短则原样返回。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def _preset_to_public(p: dict) -> dict:
    """对外返回预设时脱敏 API Key。"""
    return {
        "id": p.get("id", ""),
        "name": p.get("name", ""),
        "provider": p.get("provider", ""),
        "model": p.get("model", ""),
        "base_url": p.get("base_url", ""),
        "has_api_key": bool(p.get("api_key", "").strip()),
        "api_key_masked": _mask_api_key(p.get("api_key", "")),
        "created_at": p.get("created_at", ""),
    }


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


def _list_workspace_files(path: str, max_depth: int = 3, max_files: int = 2000) -> list[dict]:
    """安全地列出工作空间目录下的文件（限制深度、跳过隐藏目录、限制数量）。"""
    root = Path(path).resolve()
    files = []
    count = 0
    # 跳过常见的大体积无意义目录（依赖缓存、IDE 配置、版本控制元数据）
    SKIP_DIR_NAMES = {
        "__pycache__",
        "node_modules",
        ".git",
        ".svn",
        ".hg",
        ".venv",
        "venv",
        "env",
        "target",   # Rust build 缓存
        ".idea",    # JetBrains IDE 配置
        ".vscode",  # VS Code 配置
        ".next",    # Next.js build 缓存
        ".nuxt",    # Nuxt build 缓存
        ".cache",
    }

    def _scan(dir_path: Path, depth: int):
        nonlocal count
        if depth > max_depth or count >= max_files:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name in SKIP_DIR_NAMES:
                continue
            try:
                rel = entry.relative_to(root)
            except ValueError:
                continue
            is_dir = entry.is_dir()
            item = {
                "name": name,
                "path": str(entry),
                "rel": str(rel).replace("\\", "/"),
                "is_dir": is_dir,
                "size": entry.stat().st_size if entry.is_file() else 0,
            }
            files.append(item)
            count += 1
            if is_dir:
                _scan(entry, depth + 1)
            if count >= max_files:
                break

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


class _LLMCompat:
    """当 crewai 未导出 ``crewai.LLM`` 类时的兼容替代实现。

    底层基于 :mod:`langchain_openai` 的 :class:`ChatOpenAI`，提供两组能力：

    * crewai 风格 ``.call(messages)`` 接口：``/api/chat`` 直接调用；
      ``messages`` 既可以是角色/内容字典列表，也可以（作为降级）是单个字符串。
    * langchain ChatModel 原生接口（``invoke`` / ``ainvoke`` / ``stream`` 等）：
      经由 :meth:`__getattr__` 转发到内部 ``ChatOpenAI``，供 crewai 的
      ``Agent(llm=self, ...)`` 直接使用。
    """

    __slots__ = ("_llm",)

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        **extra,
    ) -> None:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": model}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        # 兼容常见温度/最大 tokens 等透传参数（未知 key 丢弃避免构造异常）
        for k, v in extra.items():
            kwargs[k] = v
        self._llm = ChatOpenAI(**kwargs)

    # ------------------------------------------------------------------
    # crewai.LLM 兼容 API
    # ------------------------------------------------------------------
    @staticmethod
    def _to_openai_content(content):
        """把 Anthropic 多模态 blocks 转换为 OpenAI vision 格式（image_url）。"""
        if not isinstance(content, list):
            return content
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image":
                src = block.get("source") or {}
                if src.get("type") == "base64":
                    media = src.get("media_type", "image/png")
                    data = src.get("data", "")
                    out.append({"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}})
                else:
                    out.append({"type": "image_url", "image_url": {"url": src.get("url", "")}})
            else:
                out.append(block)
        return out

    def call(self, messages):
        from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

        if isinstance(messages, str):
            lc_msgs: list = [HumanMessage(content=messages)]
        else:
            lc_msgs = []
            for m in messages:
                if isinstance(m, BaseMessage):
                    lc_msgs.append(m)
                    continue
                role = m.get("role") if isinstance(m, dict) else "user"
                content = self._to_openai_content(m.get("content")) if isinstance(m, dict) else str(m)
                if role in ("system",):
                    lc_msgs.append(SystemMessage(content=content))
                elif role in ("assistant", "ai"):
                    lc_msgs.append(AIMessage(content=content))
                else:
                    lc_msgs.append(HumanMessage(content=content))
        result = self._llm.invoke(lc_msgs)
        if hasattr(result, "content"):
            return result.content
        return str(result)

    # ------------------------------------------------------------------
    # 转发到 langchain ChatModel 原生接口（crewai Agent 使用）
    # ------------------------------------------------------------------
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_llm"), name)


class _AnthropicLLM:
    """Anthropic Messages API 兼容 LLM 适配器（httpx 原生调用）。

    用于 base_url 含 "anthropic" 的端点（如阿里云 MaaS token-plan 的
    /apps/anthropic 兼容端点、DeepSeek 的 /anthropic 端点等）。
    crewai.LLM 会把这类端点误判为 OpenAI 兼容，去请求不存在的
    /chat/completions，从而得到 404 "Model not found"。
    """

    __slots__ = ("model", "base_url", "api_key", "timeout")

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 180.0,
        **extra,
    ) -> None:
        self.model = model
        self.base_url = str(base_url).rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        return self.base_url + "/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    # ------------------------------------------------------------------
    # crewai.LLM 兼容 API（/api/chat 与工作流引擎调用）
    # ------------------------------------------------------------------
    def call(self, messages):
        import httpx

        system: list[str] = []
        msgs: list[dict] = []
        if isinstance(messages, str):
            msgs = [{"role": "user", "content": messages}]
        else:
            for m in messages:
                if isinstance(m, dict):
                    role = str(m.get("role", "user"))
                    content = m.get("content", "")
                else:
                    # langchain BaseMessage 兼容
                    role = getattr(m, "type", "user")
                    content = getattr(m, "content", str(m))
                if role in ("system", "developer"):
                    system.append(content if isinstance(content, str) else str(content))
                elif role in ("assistant", "ai", "tool"):
                    msgs.append({"role": "assistant", "content": content})
                else:
                    msgs.append({"role": "user", "content": content})

        payload: dict[str, object] = {"model": self.model, "max_tokens": 8192, "messages": msgs}
        if system:
            payload["system"] = "\n\n".join(system)

        resp = httpx.post(
            self._messages_url(),
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            err = resp.text[:300]
            raise ValueError(f"HTTP {resp.status_code}: {err}")

        data = resp.json()
        text_parts: list[str] = []
        fallback = ""
        for block in data.get("content") or []:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "thinking" and block.get("thinking"):
                fallback = fallback or block.get("thinking", "")
            # tool_use 等块忽略（当前对话流不使用工具）
        text = "".join(text_parts).strip()
        if not text and fallback:
            text = fallback.strip()
        return text

    # langchain / crewai 风格别名
    def invoke(self, messages, **kwargs):
        return self.call(messages)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AttributeError(
            f"_AnthropicLLM 不支持属性 {name}；如需 crewai Agent 全特性请安装 langchain-anthropic"
        )


def _build_llm(preset_id: str | None = None):
    """根据用户配置动态构建 LLM（兼容 provider/model 与裸 model 格式）。

    - preset_id 指定时，从 model_presets.json 找到对应预设，使用其 model/api_key/base_url
    - 未指定时，回退到全局 model_config.json（顶栏激活预设的写入位置）

    优先使用 crewai 自带的 ``crewai.LLM`` 包装（底层走 openai SDK）；
    若当前 crewai 版本未导出该类，则退回到基于 :mod:`langchain_openai` 的
    :class:`_LLMCompat` 适配器，保证对 ``/api/chat`` 与 crewai Agent/Crew
    两条调用路径都可用。
    """
    cfg = _load_model_config()
    if preset_id:
        # 优先用会话指定的预设
        try:
            presets_data = _load_presets()
            for p in presets_data.get("presets", []):
                if p.get("id") == preset_id:
                    pmodel = (p.get("model") or "").strip()
                    pkey = (p.get("api_key") or "").strip()
                    pbase = (p.get("base_url") or "").strip()
                    if pmodel:
                        cfg["model"] = pmodel
                    if pkey:
                        cfg["api_key"] = pkey
                    if pbase:
                        cfg["base_url"] = pbase
                    break
        except Exception:
            pass
    model = cfg.get("model") or DEFAULT_MODEL_CONFIG["model"]
    api_key = cfg.get("api_key") or os.getenv("DEEPSEEK_API_KEY", "") \
        or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
    base_url = (cfg.get("base_url") or "").strip() or None

    # Anthropic 兼容端点（如阿里云 MaaS /apps/anthropic、DeepSeek /anthropic）：
    # crewai.LLM 会误判为 OpenAI 兼容去请求 /chat/completions → 404。
    # 这里直接走 Anthropic Messages API（httpx 原生调用）。
    if base_url and "anthropic" in base_url.lower():
        return _AnthropicLLM(model, base_url=base_url, api_key=api_key)

    kwargs: dict[str, Any] = {"model": model}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key

    # 路径 1：crewai.LLM 存在（老版本 / 完整安装）
    if LLM is not None:
        try:
            return LLM(**kwargs)
        except TypeError:
            # crewai 不同版本的构造签名可能略有差异，失败则走降级路径
            pass

    # 路径 2：crewai.LLM 缺失 -> 使用 langchain_openai 兼容层
    try:
        return _LLMCompat(**kwargs)
    except Exception:
        return None

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
        # 把 Agent 执行步骤和错误日志同时输出到控制台，方便调试
        if source == "agent" or record.level in ("ERROR", "WARNING"):
            print(f"[{record.time}] [{record.level}] [{record.source}] {record.task_id or '-'} {record.message}", flush=True)
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
# SSE 流式推送用：每个 task_id 对应一个 Event，任务更新时 set()
_task_events: dict[str, threading.Event] = {}


def _notify_task_update(task_id: str) -> None:
    """通知正在监听该任务的所有 SSE 连接有新数据可用。"""
    with _tasks_lock:
        event = _task_events.get(task_id)
        if event is not None:
            event.set()


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
    if not HAS_CREWAI:
        raise RuntimeError("crewai 未正确安装，无法使用 CrewAI 功能")
    llm = _build_llm()
    if llm is None:
        raise RuntimeError("LLM 初始化失败，请检查模型配置")
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


class ChatMessage(BaseModel):
    role: str
    # content 支持纯文本或多模态 content blocks（Anthropic / OpenAI vision 格式）
    content: str | list[dict] = ""


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    stream: bool = False
    model_preset_id: str | None = None  # 会话级模型：指定时优先用该预设的 LLM 配置
    workspace_id: str | None = None  # 当前工作空间 ID，用于注入上下文


class AgentRunRequest(BaseModel):
    request: str  # 用户的 Agent 任务描述
    model_preset_id: str | None = None
    workspace_id: str | None = None
    images: list[str] = []  # 多模态图片（data URL 或 URL），传给首条用户消息


class GitCommitRequest(BaseModel):
    repo: str = ""  # 仓库地址，为空则使用当前目录 origin
    branch: str = "main"
    message: str


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


# ---------------------------------------------------------------
# 模型预设 CRUD（多套配置管理）
# ---------------------------------------------------------------
class ModelPresetRequest(BaseModel):
    name: str = ""
    provider: str = "deepseek"
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@app.get("/api/model-presets")
def list_model_presets():
    """列出所有已保存的模型预设（含当前激活 id）。API Key 已脱敏。"""
    data = _load_presets()
    return {
        "active_id": data.get("active_id", ""),
        "presets": [_preset_to_public(p) for p in data.get("presets", [])],
    }


@app.post("/api/model-presets")
def create_model_preset(req: ModelPresetRequest):
    """新建一个模型预设，并自动设为当前激活。"""
    name = req.name.strip() or f"{req.provider}/{req.model or '未命名'}"
    data = _load_presets()
    preset = {
        "id": f"preset_{uuid.uuid4().hex[:10]}",
        "name": name,
        "provider": req.provider.strip() or "deepseek",
        "model": req.model.strip(),
        "api_key": req.api_key.strip(),
        "base_url": req.base_url.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data.setdefault("presets", []).append(preset)
    data["active_id"] = preset["id"]
    _save_presets(data)
    # 同步写入 model_config.json，让运行时立即使用
    _save_model_config({
        "provider": preset["provider"],
        "model": preset["model"],
        "api_key": preset["api_key"],
        "base_url": preset["base_url"],
    })
    log_buffer.emit(
        "INFO", "system",
        f"已保存模型预设：{preset['name']}（{preset['provider']} / {preset['model']}）",
    )
    return {"ok": True, "preset": _preset_to_public(preset), "active_id": preset["id"]}


@app.put("/api/model-presets/{preset_id}")
def update_model_preset(preset_id: str, req: ModelPresetRequest):
    """更新一个已存在的预设。api_key 留空则保留原 Key。"""
    data = _load_presets()
    target = None
    for p in data.get("presets", []):
        if p.get("id") == preset_id:
            target = p
            break
    if not target:
        return JSONResponse({"ok": False, "error": "预设不存在"}, status_code=404)
    api_key = req.api_key.strip() or target.get("api_key", "")
    target["name"] = req.name.strip() or target.get("name", "")
    target["provider"] = req.provider.strip() or target.get("provider", "deepseek")
    target["model"] = req.model.strip()
    target["api_key"] = api_key
    target["base_url"] = req.base_url.strip()
    _save_presets(data)
    # 如果更新的是当前激活预设，同步 model_config.json
    if data.get("active_id") == preset_id:
        _save_model_config({
            "provider": target["provider"],
            "model": target["model"],
            "api_key": target["api_key"],
            "base_url": target["base_url"],
        })
    return {"ok": True, "preset": _preset_to_public(target)}


@app.delete("/api/model-presets/{preset_id}")
def delete_model_preset(preset_id: str):
    """删除一个预设。若删除的是当前激活，则清空 active_id。"""
    data = _load_presets()
    before = len(data.get("presets", []))
    data["presets"] = [p for p in data.get("presets", []) if p.get("id") != preset_id]
    if len(data["presets"]) == before:
        return JSONResponse({"ok": False, "error": "预设不存在"}, status_code=404)
    if data.get("active_id") == preset_id:
        data["active_id"] = ""
    _save_presets(data)
    return {"ok": True, "active_id": data.get("active_id", "")}


@app.post("/api/model-presets/{preset_id}/activate")
def activate_model_preset(preset_id: str):
    """激活一个预设（设为当前模型配置）。"""
    data = _load_presets()
    target = None
    for p in data.get("presets", []):
        if p.get("id") == preset_id:
            target = p
            break
    if not target:
        return JSONResponse({"ok": False, "error": "预设不存在"}, status_code=404)
    data["active_id"] = preset_id
    _save_presets(data)
    _save_model_config({
        "provider": target.get("provider", "deepseek"),
        "model": target.get("model", ""),
        "api_key": target.get("api_key", ""),
        "base_url": target.get("base_url", ""),
    })
    log_buffer.emit(
        "INFO", "system",
        f"已切换到预设：{target.get('name', preset_id)}",
    )
    return {
        "ok": True,
        "active_id": preset_id,
        "config": {
            "provider": target.get("provider", ""),
            "model": target.get("model", ""),
            "base_url": target.get("base_url", ""),
            "has_api_key": bool(target.get("api_key", "").strip()),
        },
    }


class TestConnectionRequest(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""


def _classify_error(err: str) -> str:
    """把 openai SDK 抛出的异常字符串翻译成用户可读的中文消息。

    触发场景：测试连接 / 任务运行时 openai 接口报错。仅依赖字符串匹配，
    不引入 openai 异常类型以避免 import 失败时崩溃。
    """
    s = err or ""
    low = s.lower()
    # 401 / 403 / incorrect api key
    if "401" in s or "invalid api key" in low or "incorrect api key" in low \
            or "authentication" in low or "auth_error" in low or "no such organization" in low:
        return "API Key 无效或未授权（请检查密钥与对应服务商）"
    # 403 / 地理位置 / 余额
    if "403" in s or "forbidden" in low or "insufficient" in low or "balance" in low \
            or "country" in low or "region" in low:
        return "访问被拒绝：可能是 Key 无权限、余额不足或所在地区不支持"
    # 404 模型不存在 / 端点不存在
    if "404" in s:
        if "model" in low or "not found" in low:
            return "模型不存在或无权访问，请检查模型名称"
        return "404 端点不存在，请检查 Base URL 和模型名称是否正确"
    # 429 限流
    if "429" in s or "rate limit" in low or "tpm" in low or "rpm" in low:
        return "请求频率超限，请稍后再试"
    # 5xx 服务端错误
    if any(code in s for code in ("500", "502", "503", "504")):
        return "模型服务端异常，请稍后重试"
    # 超时
    if "timeout" in low or "timed out" in low:
        return "请求超时，请检查网络或 Base URL"
    # 连接错误
    if "connection" in low or "connect" in low or "dns" in low or "getaddrinfo" in low \
            or "name or service not known" in low or "ssl" in low:
        return f"无法连接到模型服务：{s[:200]}"
    # 默认截断
    return s[:300] if s else "未知错误"


@app.post("/api/test-connection")
def test_connection(req: TestConnectionRequest):
    """用当前表单配置做一次极简调用验证连通性。

    自动识别 API 类型：
    - base_url 含 "anthropic" → 走 Anthropic Messages API（httpx 原生请求）
    - 其他 → 走 OpenAI SDK chat.completions

    全局 try/except 兜底：任何意外错误都以 JSON 返回。
    """
    import time
    start_total = time.perf_counter()
    try:
        cfg = _load_model_config()
        api_key = req.api_key.strip() or cfg.get("api_key") or os.getenv("DEEPSEEK_API_KEY", "") \
            or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        if not api_key:
            return {"ok": False, "error": "未配置 API Key（请在设置页填写或设置环境变量）", "latency_ms": 0}

        model = req.model.strip() or cfg.get("model") or DEFAULT_MODEL_CONFIG["model"]
        base_url = req.base_url.strip() or cfg.get("base_url") or ""
        provider = (req.provider or cfg.get("provider") or "deepseek").strip()

        # 判断是否 Anthropic 兼容端点
        is_anthropic = "anthropic" in base_url.lower()

        start = time.perf_counter()

        if is_anthropic:
            # ---- Anthropic Messages API ----
            try:
                import httpx
            except Exception:
                return {"ok": False, "error": "httpx 未安装，无法测试 Anthropic 端点", "latency_ms": 0}

            # 构造 messages 端点 URL
            url = base_url.rstrip("/")
            if not url.endswith("/v1/messages"):
                url = url + "/v1/messages"

            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": model,
                "max_tokens": 5,
                "messages": [{"role": "user", "content": "ping"}],
            }

            resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
            latency_ms = int((time.perf_counter() - start) * 1000)

            if resp.status_code == 200:
                log_buffer.emit("INFO", "system",
                    f"测试连接成功（Anthropic）：{provider} / {model}（{latency_ms} ms）")
                return {"ok": True, "latency_ms": latency_ms, "model": model, "provider": provider,
                        "api_type": "anthropic"}
            else:
                err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                msg = _classify_error(err)
                # Anthropic 404 通常是模型名错误或端点路径不对
                if resp.status_code == 404:
                    msg = f"404 端点不存在：{url}\n请检查 Base URL 是否正确（Anthropic 兼容端点应类似 https://api.deepseek.com/anthropic）"
                log_buffer.emit("WARNING", "system", f"测试连接失败（Anthropic）：{msg}")
                return {"ok": False, "error": msg, "detail": err, "latency_ms": latency_ms,
                        "api_type": "anthropic"}

        else:
            # ---- OpenAI 兼容 API ----
            try:
                import openai  # noqa: F401
            except Exception:
                return JSONResponse(
                    {"ok": False, "error": "openai SDK 未安装，无法测试", "latency_ms": 0},
                    status_code=503,
                )

            client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 15.0}
            if base_url:
                client_kwargs["base_url"] = base_url

            client = openai.OpenAI(**client_kwargs)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
                temperature=0,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            log_buffer.emit("INFO", "system",
                f"测试连接成功：{provider} / {model}（{latency_ms} ms）")
            return {"ok": True, "latency_ms": latency_ms, "model": model, "provider": provider,
                    "api_type": "openai"}

    except Exception as e:
        # 兜底：捕获所有意外异常，确保返回 JSON
        latency_ms = int((time.perf_counter() - start_total) * 1000)
        err = str(e)
        try:
            msg = _classify_error(err)
        except Exception:
            msg = err[:300] if err else "未知错误"
        log_buffer.emit("WARNING", "system", f"测试连接失败：{msg}")
        return {"ok": False, "error": msg, "detail": err[:300], "latency_ms": latency_ms}


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


def _build_skill_system_prompt(messages: list[dict]) -> str | None:
    """根据已启用的 Claude 技能构建 system prompt；@技能名 命中时注入完整指令。"""
    skills = [s for s in _load_skills() if s.get("type") == "claude" and s.get("enabled", True)]
    if not skills:
        return None
    user_text = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
    triggered = [
        s for s in skills
        if f"@{s['name']}" in user_text
        or (s.get("source", "").split("/")[-1] and f"@{s['source'].split('/')[-1]}" in user_text)
    ]
    lines = [
        "你是「淘飞AI」企业级智能体平台的助手。平台已接入以下 Claude 官方技能（来自 anthropics/skills）：",
    ]
    for s in skills:
        lines.append(f"- {s['name']}：{s.get('desc') or '（无描述）'}")
    if triggered:
        lines.append("\n用户通过 @技能名 指定了以下技能，请严格遵循技能指令执行任务：")
        for s in triggered:
            lines.append(f"\n========== 技能【{s['name']}】指令开始 ==========\n{s.get('instructions','')}\n========== 技能【{s['name']}】指令结束 ==========")
    else:
        lines.append(
            "\n当用户的请求与上述某个技能相关时，告知用户可在消息中使用「@技能名」显式调用该技能获得专业处理。"
        )
    return "\n".join(lines)


def _build_workspace_system_prompt(workspace_id: str | None) -> str | None:
    """根据 workspace_id 构建工作空间上下文 system prompt，注入文件列表和关键文件内容。"""
    if not workspace_id:
        return None
    ws_path = _workspace_path_by_id(workspace_id)
    if not ws_path:
        return None
    ws_data = _load_workspaces()
    ws_name = ""
    for ws in ws_data.get("workspaces", []):
        if ws.get("id") == workspace_id:
            ws_name = ws.get("name", "")
            break
    try:
        file_list = _list_workspace_files(ws_path, max_depth=3)
    except Exception:
        file_list = []

    lines = [f"当前工作空间信息："]
    lines.append(f"- 名称：{ws_name or workspace_id}")
    lines.append(f"- 路径：{ws_path}")
    lines.append(f"- 文件/目录列表（{len(file_list)} 项）：")

    for f in file_list:
        prefix = "📁" if f["is_dir"] else "📄"
        size_str = f" ({f['size']} bytes)" if not f["is_dir"] else ""
        lines.append(f"  {prefix} {f['rel']}{size_str}")

    context = _read_workspace_context(ws_path, max_chars=8000)
    if context:
        lines.append(f"\n工作空间关键文件内容摘要：")
        lines.append(context)

    lines.append("\n当用户询问文件、目录或项目结构时，请基于以上工作空间信息进行回答。不要说你无法访问文件系统。")
    return "\n".join(lines)


@app.post("/api/chat")
def chat(req: ChatRequest):
    """直接调用大模型接口，进行多轮对话；自动注入已启用的 Claude 技能和工作空间上下文。"""
    if not req.messages:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)
    if not HAS_CREWAI:
        return JSONResponse({"error": "LLM 功能不可用：crewai/langchain 未安装"}, status_code=503)
    try:
        llm = _build_llm(req.model_preset_id)
        if llm is None:
            return JSONResponse({"error": "LLM 初始化失败，请检查模型配置"}, status_code=500)
        # 构造适合 LLM.call 的消息列表（前端历史中 AI 消息 role 为 'ai'，需映射为 'assistant'）
        messages = [{"role": ("assistant" if m.role == "ai" else m.role), "content": m.content} for m in req.messages]
        skill_prompt = _build_skill_system_prompt(messages)
        workspace_prompt = _build_workspace_system_prompt(req.workspace_id)
        system_messages = []
        if workspace_prompt:
            system_messages.append(workspace_prompt)
        if skill_prompt:
            system_messages.append(skill_prompt)
        if system_messages:
            messages = [{"role": "system", "content": "\n\n".join(system_messages)}] + messages
        try:
            reply_text = llm.call(messages)
        except TypeError:
            # 极少数老版本 crewai 可能仅支持字符串，退化为单条 prompt
            reply_text = llm.call("\n".join(f"{m['role']}: {m['content']}" for m in messages))
        if not isinstance(reply_text, str):
            reply_text = str(reply_text)
        log_buffer.emit(
            "INFO", "system",
            f"对话中心调用 LLM：{len(messages)} 条消息"
            f"{'（含工作空间上下文）' if workspace_prompt else ''}"
            f"{'（含 Claude 技能上下文）' if skill_prompt else ''} -> 回复 {len(reply_text)} 字符",
        )
        return {"reply": reply_text, "skills_injected": bool(skill_prompt), "workspace_injected": bool(workspace_prompt)}
    except Exception as e:
        err_msg = str(e)
        log_buffer.emit("ERROR", "system", f"对话中心 LLM 调用失败：{err_msg}")
        return JSONResponse({"error": err_msg}, status_code=500)


# ---------------------------------------------------------------
# 集成管理 - 天气查询（Open-Meteo，免费无需 API Key）
# ---------------------------------------------------------------
WEATHER_CODE_MAP = {
    0: "晴", 1: "基本晴", 2: "局部多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "小阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def _http_get_json(url: str, timeout: int = 10) -> dict:
    """GET 请求并解析 JSON（urllib 标准库实现，避免额外依赖）。"""
    import urllib.parse
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (taofei-app)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@app.get("/api/integrations/weather")
def integration_weather(city: str = Query(..., min_length=1)):
    """天气查询集成：城市名 -> 当前天气 + 3 天预报（Open-Meteo）。"""
    import urllib.parse

    city = city.strip()
    if not city:
        return JSONResponse({"error": "城市名不能为空"}, status_code=400)
    try:
        # 1. 城市名 -> 经纬度
        geo = _http_get_json(
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={urllib.parse.quote(city)}&count=1&language=zh&format=json"
        )
        results = geo.get("results") or []
        if not results:
            return JSONResponse({"error": f"未找到城市「{city}」，请检查名称（如：北京、上海、Shanghai）"}, status_code=404)
        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        # 2. 经纬度 -> 天气
        wx = _http_get_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min&forecast_days=4&timezone=auto"
        )
        cur = wx.get("current", {})
        daily = wx.get("daily", {})
        code = cur.get("weather_code", 0)
        result = {
            "city": loc.get("name", city),
            "admin1": loc.get("admin1", ""),
            "country": loc.get("country", ""),
            "current": {
                "temperature": cur.get("temperature_2m"),
                "feels_like": cur.get("apparent_temperature"),
                "humidity": cur.get("relative_humidity_2m"),
                "wind_speed": cur.get("wind_speed_10m"),
                "condition": WEATHER_CODE_MAP.get(code, f"未知({code})"),
            },
            "daily": [],
        }
        dates = daily.get("time", [])
        for i, d in enumerate(dates):
            dcode = daily.get("weather_code", [])[i] if i < len(daily.get("weather_code", [])) else 0
            result["daily"].append({
                "date": d,
                "condition": WEATHER_CODE_MAP.get(dcode, "未知"),
                "max": daily.get("temperature_2m_max", [])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
                "min": daily.get("temperature_2m_min", [])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
            })
        log_buffer.emit("INFO", "system", f"天气集成查询：{city} -> {result['current']['condition']} {result['current']['temperature']}°C")
        return result
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        log_buffer.emit("ERROR", "system", f"天气集成查询失败：{err}")
        return JSONResponse({"error": f"查询失败：{err}"}, status_code=500)


@app.get("/api/integrations")
def list_integrations():
    """集成管理列表：天气查询已接入，其余为规划中。"""
    return {
        "integrations": [
            {"id": "weather", "name": "天气查询", "icon": "🌤️", "status": "connected",
             "desc": "Open-Meteo 天气 API，支持全球城市实时天气与 4 日预报，无需 API Key", "category": "数据服务"},
            {"id": "wecom", "name": "企业微信", "icon": "💬", "status": "planned", "desc": "消息推送、群机器人通知", "category": "协同办公"},
            {"id": "dingtalk", "name": "钉钉", "icon": "📎", "status": "planned", "desc": "待办同步、工作通知", "category": "协同办公"},
            {"id": "feishu", "name": "飞书", "icon": "🐦", "status": "planned", "desc": "文档读写、消息卡片", "category": "协同办公"},
            {"id": "crm", "name": "CRM 系统", "icon": "👥", "status": "planned", "desc": "客户数据查询、商机跟进", "category": "业务系统"},
            {"id": "database", "name": "数据库", "icon": "🗄️", "status": "planned", "desc": "SQL 查询、数据同步", "category": "数据服务"},
        ]
    }


# ---------------------------------------------------------------
# 集成管理 - 技能管理（HTTP API 技能 + Claude 技能 SKILL.md，持久化到 skills.json）
# ---------------------------------------------------------------
SKILLS_FILE = EXE_DIR / "skills.json"
CLAUDE_SKILLS_REPO = "anthropics/skills"


def _load_skills() -> list[dict]:
    try:
        if SKILLS_FILE.exists():
            with open(SKILLS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [s for s in data if isinstance(s, dict)]
    except Exception:
        pass
    return []


def _save_skills(skills: list[dict]) -> None:
    try:
        with open(SKILLS_FILE, "w", encoding="utf-8") as f:
            json.dump(skills, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        log_buffer.emit("ERROR", "system", f"保存技能配置失败：{exc}")


class SkillRequest(BaseModel):
    id: str = ""
    type: str = "http"          # http: HTTP API 技能；claude: Claude 技能（SKILL.md）
    name: str
    icon: str = "⚡"
    desc: str = ""
    method: str = "GET"
    url: str = ""
    headers: str = ""
    body: str = ""
    instructions: str = ""      # claude 类型：SKILL.md 指令内容
    enabled: bool = True


def _parse_skill_md(text: str) -> tuple[str, str, str]:
    """解析 SKILL.md：返回 (name, description, 指令正文)。无 frontmatter 时降级处理。"""
    name, desc = "", ""
    body = text
    if text.lstrip().startswith("---"):
        parts = text.lstrip().split("---", 2)
        if len(parts) >= 3:
            meta, body = parts[1], parts[2]
            for line in meta.splitlines():
                line = line.strip()
                low = line.lower()
                if low.startswith("name:"):
                    name = line[5:].strip().strip('"').strip("'")
                elif low.startswith("description:"):
                    desc = line[12:].strip().strip('"').strip("'")
    return name, desc, body.strip()


@app.get("/api/skills")
def list_skills():
    """技能列表。"""
    return {"skills": _load_skills()}


@app.post("/api/skills")
def save_skill(req: SkillRequest):
    """新建或更新技能（id 为空则新建）。支持 HTTP API 技能与 Claude 技能两种类型。"""
    name = req.name.strip()
    if not name:
        return JSONResponse({"error": "技能名称不能为空"}, status_code=400)
    skill_type = req.type if req.type in ("http", "claude") else "http"
    if skill_type == "claude":
        instructions = req.instructions.strip()
        if not instructions:
            return JSONResponse({"error": "SKILL.md 指令内容不能为空"}, status_code=400)
        # 若粘贴了完整 SKILL.md（带 frontmatter），自动解析 name/description
        md_name, md_desc, md_body = _parse_skill_md(instructions)
        skill = {
            "id": req.id.strip() or ("skill_" + uuid.uuid4().hex[:10]),
            "type": "claude",
            "name": name,
            "icon": req.icon.strip() or "🧩",
            "desc": req.desc.strip() or md_desc,
            "method": "",
            "url": "",
            "headers": "",
            "body": "",
            "instructions": md_body or instructions,
            "enabled": req.enabled,
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        }
    else:
        url = req.url.strip()
        if not url:
            return JSONResponse({"error": "请求 URL 不能为空"}, status_code=400)
        if req.method.upper() not in ("GET", "POST", "PUT", "DELETE"):
            return JSONResponse({"error": "请求方式仅支持 GET/POST/PUT/DELETE"}, status_code=400)
        # 校验 headers / body JSON 格式
        for field_name, raw in (("headers", req.headers), ("body", req.body)):
            if raw and raw.strip():
                try:
                    json.loads(raw)
                except Exception:
                    return JSONResponse({"error": f"{field_name} 不是合法的 JSON"}, status_code=400)
        skill = {
            "id": req.id.strip() or ("skill_" + uuid.uuid4().hex[:10]),
            "type": "http",
            "name": name,
            "icon": req.icon.strip() or "⚡",
            "desc": req.desc.strip(),
            "method": req.method.upper(),
            "url": url,
            "headers": req.headers.strip(),
            "body": req.body.strip(),
            "instructions": "",
            "enabled": req.enabled,
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        }
    skills = _load_skills()
    for i, s in enumerate(skills):
        if s.get("id") == skill["id"]:
            skills[i] = skill
            break
    else:
        skills.insert(0, skill)
    _save_skills(skills)
    log_buffer.emit("INFO", "system", f"技能已保存：{name}（{'Claude 技能' if skill_type == 'claude' else req.method.upper() + ' ' + url}）")
    return {"ok": True, "skill": skill}


@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: str):
    skills = _load_skills()
    remaining = [s for s in skills if s.get("id") != skill_id]
    if len(remaining) == len(skills):
        return JSONResponse({"error": "技能不存在"}, status_code=404)
    _save_skills(remaining)
    log_buffer.emit("INFO", "system", f"技能已删除：{skill_id}")
    return {"ok": True}


@app.post("/api/skills/{skill_id}/run")
def run_skill(skill_id: str):
    """执行（测试）一个技能：HTTP 技能发起真实请求；Claude 技能返回 SKILL.md 指令预览。"""
    import urllib.error
    import urllib.request

    skill = next((s for s in _load_skills() if s.get("id") == skill_id), None)
    if not skill:
        return JSONResponse({"error": "技能不存在"}, status_code=404)
    if skill.get("type") == "claude":
        return {"ok": True, "type": "claude",
                "response": f"# {skill.get('name','')}\n\n{skill.get('desc','')}\n\n---\n\n{skill.get('instructions','')}"}
    url = skill.get("url", "")
    method = skill.get("method", "GET").upper()
    headers = {}
    if skill.get("headers"):
        try:
            headers = json.loads(skill["headers"])
        except Exception:
            return JSONResponse({"error": "headers 配置不是合法 JSON"}, status_code=400)
    body = skill.get("body") or ""
    data = None
    if method in ("POST", "PUT") and body:
        data = body.encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    try:
        r = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (taofei-app)", **headers}, method=method)
        with urllib.request.urlopen(r, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "response": text[:8000]}
    except urllib.error.HTTPError as e:
        return JSONResponse({"error": f"HTTP {e.code}：{e.reason}", "response": e.read().decode('utf-8', errors='replace')[:2000]}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"请求失败：{exc}"}, status_code=500)


# ---------------------------------------------------------------
# Claude Code 官方技能市场（anthropics/skills）
# ---------------------------------------------------------------
def _fetch_skill_md(skill_dir: str) -> str:
    """从官方仓库下载 skills/<dir>/SKILL.md 原文。"""
    import urllib.request

    url = f"https://raw.githubusercontent.com/{CLAUDE_SKILLS_REPO}/main/skills/{skill_dir}/SKILL.md"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (taofei-app)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


@app.get("/api/skills/claude-official")
def claude_official_skills():
    """列出 anthropics/skills 官方仓库中的可用技能目录。"""
    try:
        tree = _http_get_json(
            f"https://api.github.com/repos/{CLAUDE_SKILLS_REPO}/git/trees/main?recursive=1",
            timeout=15,
        )
        dirs = []
        for item in tree.get("tree", []):
            p = item.get("path", "")
            if p.startswith("skills/") and p.endswith("/SKILL.md") and p.count("/") == 2:
                dirs.append(p.split("/")[1])
        existing = {s.get("name") for s in _load_skills()}
        return {"repo": CLAUDE_SKILLS_REPO, "skills": sorted(dirs), "imported": sorted(existing)}
    except Exception as exc:  # noqa: BLE001
        log_buffer.emit("ERROR", "system", f"拉取官方技能列表失败：{exc}")
        return JSONResponse({"error": f"拉取官方技能列表失败：{exc}"}, status_code=502)


class ImportClaudeRequest(BaseModel):
    names: list[str]


@app.post("/api/skills/import-claude")
def import_claude_skills(req: ImportClaudeRequest):
    """批量导入官方技能：下载 SKILL.md、解析 frontmatter、写入 skills.json。"""
    if not req.names:
        return JSONResponse({"error": "请至少选择一个技能"}, status_code=400)
    skills = _load_skills()
    imported, failed = [], []
    for name in req.names[:30]:
        try:
            md = _fetch_skill_md(name)
            md_name, md_desc, md_body = _parse_skill_md(md)
            display_name = md_name or name
            # 已存在同名技能则更新
            skill = {
                "id": "skill_" + uuid.uuid4().hex[:10],
                "type": "claude",
                "name": display_name,
                "icon": "🧩",
                "desc": md_desc,
                "method": "", "url": "", "headers": "", "body": "",
                "instructions": md_body or md,
                "enabled": True,
                "source": f"{CLAUDE_SKILLS_REPO}/skills/{name}",
                "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            }
            for i, s in enumerate(skills):
                if s.get("name") == display_name and s.get("type") == "claude":
                    skill["id"] = s["id"]
                    skills[i] = skill
                    break
            else:
                skills.insert(0, skill)
            imported.append(display_name)
        except Exception as exc:  # noqa: BLE001
            failed.append({"name": name, "error": str(exc)})
    _save_skills(skills)
    log_buffer.emit("INFO", "system", f"导入 Claude 官方技能 {len(imported)} 个：{'、'.join(imported)}")
    return {"ok": True, "imported": imported, "failed": failed}


# ---------------------------------------------------------------
# 任务编排 - 可视化工作流（自研引擎，架构对齐 Dify workflow）
#   图 DAG + 变量池 + 节点执行器，支持导入 Dify DSL
# ---------------------------------------------------------------
WORKFLOWS_FILE = EXE_DIR / "workflows.json"

try:
    from wf_engine import WorkflowEngine  # noqa: E402
    from wf_engine.dsl import convert_dify_dsl  # noqa: E402
    HAS_WF_ENGINE = True
except ImportError:
    WorkflowEngine = None  # type: ignore
    convert_dify_dsl = None  # type: ignore
    HAS_WF_ENGINE = False

try:
    from agent_runner import create_agent_task_id, run_agent_task  # noqa: E402
    HAS_AGENT_RUNNER = True
except ImportError:
    create_agent_task_id = None  # type: ignore
    run_agent_task = None  # type: ignore
    HAS_AGENT_RUNNER = False


def _load_workflows() -> list[dict]:
    try:
        if WORKFLOWS_FILE.exists():
            with open(WORKFLOWS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_workflows(items: list[dict]) -> None:
    with open(WORKFLOWS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


class WorkflowRequest(BaseModel):
    id: str = ""
    name: str
    desc: str = ""
    graph: dict


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = {}


class WorkflowDslRequest(BaseModel):
    name: str = ""
    dsl: str


@app.get("/api/workflows")
def list_workflows():
    return {"workflows": _load_workflows()}


@app.get("/api/workflows/{wf_id}")
def get_workflow(wf_id: str):
    wf = next((w for w in _load_workflows() if w.get("id") == wf_id), None)
    if not wf:
        return JSONResponse({"error": "工作流不存在"}, status_code=404)
    return wf


@app.post("/api/workflows")
def save_workflow(req: WorkflowRequest):
    name = req.name.strip()
    if not name:
        return JSONResponse({"error": "名称不能为空"}, status_code=400)
    if not isinstance(req.graph, dict) or not req.graph.get("nodes"):
        return JSONResponse({"error": "graph 必须包含 nodes"}, status_code=400)
    items = _load_workflows()
    wf_id = req.id.strip() or ("wf_" + uuid.uuid4().hex[:10])
    wf = {
        "id": wf_id,
        "name": name,
        "desc": req.desc.strip(),
        "graph": req.graph,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    for i, item in enumerate(items):
        if item.get("id") == wf_id:
            items[i] = wf
            break
    else:
        items.insert(0, wf)
    _save_workflows(items)
    log_buffer.emit("INFO", "system", f"工作流已保存：{name}（{len(req.graph.get('nodes', []))} 个节点）")
    return wf


@app.delete("/api/workflows/{wf_id}")
def delete_workflow(wf_id: str):
    items = _load_workflows()
    rest = [w for w in items if w.get("id") != wf_id]
    if len(rest) == len(items):
        return JSONResponse({"error": "工作流不存在"}, status_code=404)
    _save_workflows(rest)
    return {"ok": True}


def _run_workflow_async(task_id: str, wf: dict, inputs: dict[str, Any]):
    """后台线程执行工作流引擎，日志写入 log_buffer（带 task_id），节点进度实时写入任务状态。"""
    try:
        with _tasks_lock:
            _tasks[task_id]["status"] = "running"
        log_buffer.emit("INFO", "system", f"工作流「{wf['name']}」开始执行", task_id)

        if not HAS_WF_ENGINE:
            raise RuntimeError("wf_engine 工作流引擎未安装")

        if not HAS_CREWAI:
            raise RuntimeError("LLM 功能不可用：crewai/langchain 未安装")

        llm = _build_llm()
        if llm is None:
            raise RuntimeError("LLM 初始化失败，请检查模型配置")

        def llm_call(messages: list[dict]) -> str:
            try:
                result = llm.call(messages)
            except TypeError:
                result = llm.call("\n".join(f"{m['role']}: {m['content']}" for m in messages))
            return result if isinstance(result, str) else str(result)

        def wlog(level: str, message: str) -> None:
            log_buffer.emit(level, "workflow", message, task_id)

        # 节点进度回调：node_runs 实时可查（前端轮询 /api/status/{task_id} 高亮画布）
        progress_map: dict[str, dict] = {}

        def on_progress(record: dict) -> None:
            progress_map[record["id"]] = record
            with _tasks_lock:
                _tasks[task_id]["node_runs"] = list(progress_map.values())

        def get_skill(skill_id: str):
            return next((s for s in _load_skills() if s.get("id") == skill_id), None)

        engine = WorkflowEngine(
            wf.get("graph", {}),
            llm_call=llm_call, log=wlog, python_bin=sys.executable,
            progress=on_progress, extra_ctx={"get_skill": get_skill},
        )
        result = engine.run(inputs)
        with _tasks_lock:
            _tasks[task_id].update(
                status="completed",
                result=result.get("outputs", {}),
                node_runs=result.get("node_runs", []),
                skipped=result.get("skipped", []),
            )
        log_buffer.emit("INFO", "system", f"工作流「{wf['name']}」执行完成", task_id)
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        log_buffer.emit("ERROR", "system", f"工作流执行失败：{err_msg}", task_id)
        with _tasks_lock:
            _tasks[task_id].update(status="failed", error=err_msg)


@app.post("/api/workflows/{wf_id}/run")
def run_workflow(wf_id: str, req: WorkflowRunRequest):
    wf = next((w for w in _load_workflows() if w.get("id") == wf_id), None)
    if not wf:
        return JSONResponse({"error": "工作流不存在"}, status_code=404)
    task_id = uuid.uuid4().hex[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "topic": f"[工作流] {wf['name']}",
            "status": "queued",
            "workspace_id": "",
            "result": None,
            "error": None,
            "node_runs": [],
        }
    log_buffer.emit("INFO", "system", f"收到工作流任务：{wf['name']}", task_id)
    threading.Thread(target=_run_workflow_async, args=(task_id, wf, req.inputs), daemon=True).start()
    return {"task_id": task_id}


@app.post("/api/workflows/import-dsl")
def import_workflow_dsl(req: WorkflowDslRequest):
    if not HAS_WF_ENGINE:
        return JSONResponse({"error": "wf_engine 工作流引擎未安装，无法导入 DSL"}, status_code=503)
    try:
        graph, warnings = convert_dify_dsl(req.dsl)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    name = (req.name or "").strip() or "导入的 Dify 工作流"
    wf = save_workflow(WorkflowRequest(name=name, desc="从 Dify DSL 导入", graph=graph))
    log_buffer.emit("INFO", "system", f"Dify DSL 导入完成：{name}，警告 {len(warnings)} 条")
    return {"workflow": wf, "warnings": warnings}


@app.get("/api/status/{task_id}")
def task_status(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return task


@app.get("/api/agent/stream/{task_id}")
def agent_stream(task_id: str):
    """Server-Sent Events：实时推送 Agent 任务更新，取代轮询。"""

    def event_generator():
        last_snapshot = None
        while True:
            with _tasks_lock:
                event = _task_events.setdefault(task_id, threading.Event())
                event.clear()
                task = _tasks.get(task_id)
            if not task:
                yield f"event: error\ndata: {json.dumps({'error': '任务不存在'}, ensure_ascii=False)}\n\n"
                break
            status = task.get("status")
            # 快照关键字段：状态、当前步骤、结果、步数；任一变化即推送，
            # 确保前端能看到"思考第 N 步"等中间过程，而非只在 result 变化时才更新
            snapshot = (
                status,
                task.get("current_step"),
                task.get("result"),
                len(task.get("steps") or []),
            )
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                if status in ("completed", "failed"):
                    yield f"event: done\ndata: {json.dumps(task, ensure_ascii=False)}\n\n"
                    break
                yield f"data: {json.dumps(task, ensure_ascii=False)}\n\n"
            elif status in ("completed", "failed"):
                yield f"event: done\ndata: {json.dumps(task, ensure_ascii=False)}\n\n"
                break
            # 等待下一次更新（最长 5 秒唤醒一次，避免连接僵死）
            timed_out = not event.wait(timeout=5.0)
            if timed_out:
                # 心跳：保持连接存活，防止代理/浏览器因空闲断开
                yield ": heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------
# Agent（ReAct 循环）
# ---------------------------------------------------------------
def _run_agent_async(task_id: str, user_request: str, workspace_path: str | None, model_preset_id: str | None, images: list[str] | None = None):
    """后台线程执行 ReAct Agent。"""
    try:
        with _tasks_lock:
            _tasks[task_id]["status"] = "running"
        log_buffer.emit("INFO", "system", f"Agent 任务开始：{user_request[:80]}", task_id)

        if not HAS_AGENT_RUNNER:
            raise RuntimeError("agent_runner 未安装")
        if not HAS_CREWAI:
            raise RuntimeError("LLM 功能不可用：crewai/langchain 未安装")

        llm = _build_llm(model_preset_id)
        if llm is None:
            raise RuntimeError("LLM 初始化失败，请检查模型配置")

        def llm_call(messages: list[dict]) -> str:
            try:
                result = llm.call(messages)
            except TypeError:
                result = llm.call("\n".join(f"{m['role']}: {m['content']}" for m in messages))
            return result if isinstance(result, str) else str(result)

        def emit_log(level: str, message: str, tid: str):
            log_buffer.emit(level, "agent", message, tid)

        def notify_update():
            _notify_task_update(task_id)

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
        )
    except Exception as exc:
        err_msg = str(exc)
        log_buffer.emit("ERROR", "system", f"Agent 任务失败：{err_msg}", task_id)
        with _tasks_lock:
            _tasks[task_id].update(status="failed", error=err_msg)


@app.post("/api/agent/run")
def agent_run(req: AgentRunRequest):
    """启动一个 ReAct Agent 任务，返回 task_id 供前端轮询。"""
    if not req.request.strip():
        return JSONResponse({"error": "任务描述不能为空"}, status_code=400)
    if not HAS_AGENT_RUNNER:
        return JSONResponse({"error": "Agent 功能不可用：agent_runner 未安装"}, status_code=503)
    if not HAS_CREWAI:
        return JSONResponse({"error": "LLM 功能不可用：crewai/langchain 未安装"}, status_code=503)

    task_id = create_agent_task_id()
    workspace_path = _workspace_path_by_id(req.workspace_id) if req.workspace_id else None
    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "topic": req.request[:60],
            "status": "queued",
            "workspace_id": req.workspace_id or "",
            "result": None,
            "error": None,
            "steps": [],
            "current_step": "",
            "type": "agent",
        }
    log_buffer.emit("INFO", "system", f"收到 Agent 任务：{req.request[:60]}", task_id)
    threading.Thread(
        target=_run_agent_async,
        args=(task_id, req.request, workspace_path, req.model_preset_id, req.images or []),
        daemon=True,
    ).start()
    return {"task_id": task_id}


@app.get("/api/git/status")
def git_status():
    """查询当前 Git 工作区是否有可提交的变更。"""
    import subprocess

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return JSONResponse({"error": f"git status 失败：{res.stderr}"}, status_code=500)
        changes = [line for line in res.stdout.strip().splitlines() if line.strip()]
        return {"clean": len(changes) == 0, "changes": changes}
    except Exception as exc:
        return JSONResponse({"error": f"查询状态失败：{str(exc)}"}, status_code=500)


@app.post("/api/git/commit")
def git_commit(req: GitCommitRequest):
    """将当前工作目录的变更提交并推送到 GitHub。"""
    import subprocess

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    message = req.message.strip()
    if not message:
        return JSONResponse({"error": "提交信息不能为空"}, status_code=400)

    try:
        # 检查工作区状态
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if status_res.returncode != 0:
            return JSONResponse({"error": f"git status 失败：{status_res.stderr}"}, status_code=500)
        if not status_res.stdout.strip():
            return JSONResponse({"error": "没有可提交的变更"}, status_code=400)

        # 添加、提交、推送
        subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True, text=True)
        commit_res = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_res.returncode != 0:
            return JSONResponse({"error": f"提交失败：{commit_res.stderr}"}, status_code=500)
        commit_hash = commit_res.stdout.splitlines()[0] if commit_res.stdout else ""

        branch = req.branch.strip() or "main"
        push_res = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if push_res.returncode != 0:
            return JSONResponse({"error": f"推送失败：{push_res.stderr}", "commit": commit_hash}, status_code=500)

        log_buffer.emit("INFO", "system", f"Git 提交并推送成功：{message[:50]}")
        return {
            "ok": True,
            "commit": commit_hash,
            "branch": branch,
            "output": (push_res.stdout or "已推送").strip(),
        }
    except subprocess.CalledProcessError as exc:
        return JSONResponse({"error": f"Git 命令失败：{exc.stderr}"}, status_code=500)
    except Exception as exc:
        return JSONResponse({"error": f"提交异常：{str(exc)}"}, status_code=500)


@app.get("/api/tasks")
def list_tasks(workspace_id: str | None = Query(None)):
    # 倒序返回,最多 50 个;可按 workspace_id 过滤
    tasks = sorted(_tasks.values(), key=lambda t: t["id"], reverse=True)
    if workspace_id:
        tasks = [t for t in tasks if t.get("workspace_id") == workspace_id]
    return {"tasks": tasks[:50]}


@app.post("/api/tasks/clear")
def clear_tasks():
    """清空当前会话的任务历史（内存中）。"""
    with _tasks_lock:
        _tasks.clear()
    log_buffer.emit("INFO", "system", "已清空所有任务历史")
    return {"ok": True}


@app.get("/api/dashboard/stats")
def dashboard_stats():
    """企业级仪表盘：核心统计指标。"""
    total = len(_tasks)
    completed = sum(1 for t in _tasks.values() if t["status"] == "completed")
    running = sum(1 for t in _tasks.values() if t["status"] in ("running", "queued"))
    failed = sum(1 for t in _tasks.values() if t["status"] == "failed")
    # 模拟节省工时：每个已完成任务按 0.5h 估算
    saved_hours = completed * 0.5 + round(len(_tasks) * 0.1, 1)
    return {
        "agents": 2,  # 研究员 + 分析师双 Agent
        "today_tasks": total,  # 会话周期内任务数
        "success_rate": round((completed / max(total, 1)) * 100, 1),
        "saved_hours": int(saved_hours),
        "running": running,
        "completed": completed,
        "failed": failed,
        "total": total,
    }


@app.get("/api/dashboard/agents")
def dashboard_agents():
    """热门智能体卡片列表。"""
    return {
        "agents": [
            {"id": "cs", "name": "客服智能体", "icon": "🎧", "desc": "7×24h 客户咨询、投诉处理与工单生成", "color": "#3b82f6", "runs": 128},
            {"id": "sales", "name": "销售助手", "icon": "💼", "desc": "商机挖掘、客户画像分析与跟进建议", "color": "#8b5cf6", "runs": 96},
            {"id": "analyst", "name": "经营分析师", "icon": "📊", "desc": "经营数据解读、趋势预测与决策建议", "color": "#10b981", "runs": 84},
            {"id": "doc", "name": "文档助手", "icon": "📄", "desc": "合同/报告/标书起草、审阅与知识提炼", "color": "#f59e0b", "runs": 72},
            {"id": "flow", "name": "流程自动化", "icon": "⚙️", "desc": "跨系统流程编排、数据同步与审批自动化", "color": "#ef4444", "runs": 56},
        ]
    }


@app.get("/api/dashboard/trend")
def dashboard_trend():
    """近 7 天任务趋势（mock，基于真实任务分布生成）。"""
    from collections import Counter
    from datetime import datetime, timedelta

    today = datetime.now(timezone.utc).date()
    counts = Counter()
    for t in _tasks.values():
        # task id 前 8 位是十六进制时间戳近似，fallback 到今天
        try:
            ts = int(t["id"][:8], 16)
            d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except Exception:
            d = today
        counts[d.isoformat()] += 1
    labels = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    data = [counts.get(d, 0) for d in labels]
    # 若没有真实数据，补一点 mock 趋势让图表不空
    if sum(data) == 0:
        data = [12, 18, 15, 22, 28, 24, 32]
    return {"labels": labels, "data": data}


@app.get("/api/dashboard/activities")
def dashboard_activities(limit: int = Query(10, ge=1, le=50)):
    """最近动态流。"""
    recent = sorted(_tasks.values(), key=lambda t: t["id"], reverse=True)[:limit]
    items = []
    for t in recent:
        if t["status"] == "completed":
            text = f"任务「{t['topic'][:30]}...」已完成"
            tag = "完成"
            color = "#10b981"
        elif t["status"] == "failed":
            text = f"任务「{t['topic'][:30]}...」执行失败"
            tag = "失败"
            color = "#ef4444"
        else:
            text = f"任务「{t['topic'][:30]}...」执行中"
            tag = "运行"
            color = "#3b82f6"
        items.append({"id": t["id"], "text": text, "tag": tag, "color": color, "status": t["status"]})
    if not items:
        items = [
            {"id": "1", "text": "企业级AI智能体平台已就绪", "tag": "系统", "color": "#3b82f6", "status": "ok"},
            {"id": "2", "text": "可输入主题让研究员 + 分析师双 Agent 协作", "tag": "提示", "color": "#8b5cf6", "status": "ok"},
        ]
    return {"activities": items}


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
def list_workspace_files_api(workspace_id: str, max_depth: int = Query(4, ge=1, le=10), max_files: int = Query(2000, ge=1, le=20000)):
    data = _load_workspaces()
    ws = next((w for w in data.get("workspaces", []) if w.get("id") == workspace_id), None)
    if not ws:
        return JSONResponse({"error": "工作空间不存在"}, status_code=404)
    path = ws.get("path")
    if not path or not Path(path).exists():
        return JSONResponse({"error": "工作空间目录不存在"}, status_code=400)
    try:
        files = _list_workspace_files(path, max_depth=max_depth, max_files=max_files)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"读取目录失败：{exc}"}, status_code=500)
    return {"files": files}


def _can_show_gui_on_windows() -> bool:
    """判断当前进程运行的 Windows 会话是否允许显示可见的 GUI 对话框。

    返回 True 的条件：Windows 平台 + 运行在非 Session 0（Session 0 为服务/沙箱会话，
    UI 仅能在「交互会话」显示，通常 SessionId >= 1）。
    Linux/macOS 下默认返回 False，避免弹出无窗口。
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        # ProcessIdToSessionId: kernel32 原生 API，WinXP+ 均可用
        session_id = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.ProcessIdToSessionId(
            ctypes.c_ulong(os.getpid()),
            ctypes.byref(session_id),
        )
        if not ok:
            # 取不到时保守认为不能显示，退回 prompt 粘贴路径
            return False
        return session_id.value > 0
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/browse-directory")
def browse_directory():
    """弹出系统目录选择对话框，返回用户选择的目录路径。

    - Windows + 交互桌面会话：用 PowerShell 调 OpenFileDialog（ValidateNames=False hack）
      实现现代 Windows 资源管理器风格的文件夹选择对话框。
      通过 TopMost 属主窗体置顶（否则弹窗会落到其它窗口后面），并声明 DPI 感知
      （否则高分屏缩放下对话框会被系统位图拉伸放大）
    - 其它环境：返回 ``{ unsupported: true }``，前端会退回"粘贴路径"方式，避免
      请求阻塞在 UI 无法显示的环境里。
    - 接口会阻塞等待用户在弹窗完成选择；取消 / 超时返回 ``{ canceled: true }``
    """
    if not _can_show_gui_on_windows():
        return {"unsupported": True, "canceled": False, "path": ""}
    try:
        import shutil
        ps_exe = shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        if not os.path.isfile(ps_exe):
            return {"unsupported": True, "canceled": False, "path": "", "reason": "powershell.exe not found"}

        # 开发模式 BASE_DIR=项目根，脚本在 backend/ 下；打包模式 BASE_DIR=_MEIPASS，
        # 脚本由 spec 打包到 _MEIPASS/backend/ 下，两种模式路径一致。
        script_path = BASE_DIR / "backend" / "browse_directory.ps1"
        if not script_path.exists():
            return {"unsupported": True, "canceled": False, "path": "", "reason": "browse_directory.ps1 not found"}

        result = subprocess.run(
            [ps_exe, "-Sta", "-WindowStyle", "Hidden", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            check=False,
        )
        path = (result.stdout or "").strip()
        if not path or path == "Folder Selection.":
            return {"unsupported": False, "canceled": True, "path": ""}
        normalized = _normalize_workspace_path(path)
        return {"unsupported": False, "canceled": False, "path": normalized}
    except subprocess.TimeoutExpired:
        return {"unsupported": False, "canceled": True, "path": ""}
    except Exception as exc:  # noqa: BLE001
        # 任何异常都按"不支持原生对话框"返回，让前端走粘贴路径兜底，不向前端抛 500
        return {"unsupported": True, "canceled": False, "path": "", "reason": str(exc)}


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

# Vue3 前端使用相对路径 (./assets/...)，将 frontend 目录挂载到根路径
# 使用 HTML 模式：找不到文件时回退到 index.html（支持 Vue Router history 模式）
# API 路由已在上方定义，会优先匹配
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


# ---------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------
def main():
    import socket
    import webbrowser

    # --no-browser: Electron 模式下不自动打开浏览器
    no_browser = "--no-browser" in sys.argv

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

    # Electron 通过 stdout 解析此行获取端口
    print(f"__BACKEND_PORT__:{port}", flush=True)

    if not no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
