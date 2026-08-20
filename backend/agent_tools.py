"""Agent 工具集：供 ReAct 循环调用的本地工具。

每个工具都是一个普通函数，签名统一为：
    tool_name(workspace_path: str | None, **kwargs) -> dict
返回字典必须包含 "observation" 键（字符串），可选 "error" 键表示失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

MAX_FILE_SIZE = 200_000
MAX_OUTPUT_LEN = 4000


def _safe_path(workspace_path: str | None, rel: str) -> Path:
    """把相对路径限制在工作空间内，防止越界访问。"""
    if not workspace_path:
        raise ValueError("没有可用的工作空间，无法操作文件")
    root = Path(workspace_path).resolve()
    target = (root / rel).resolve()
    # 确保 target 在 root 之下
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径越界：{rel}") from exc
    return target


def _short(text: Any, n: int = MAX_OUTPUT_LEN) -> str:
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    if len(s) <= n:
        return s
    return s[:n] + f"\n...[共 {len(s)} 字符，已截断]"


# ------------------------------------------------------------------
# 工具实现
# ------------------------------------------------------------------
def read_file(workspace_path: str | None, path: str) -> dict:
    """读取工作空间内指定文本文件的内容。"""
    try:
        target = _safe_path(workspace_path, path)
        if not target.exists():
            return {"observation": f"文件不存在：{path}"}
        if not target.is_file():
            return {"observation": f"路径不是文件：{path}"}
        size = target.stat().st_size
        if size > MAX_FILE_SIZE:
            return {"observation": f"文件过大（{size} bytes），只返回路径：{path}"}
        content = target.read_text(encoding="utf-8", errors="ignore")
        return {"observation": f"--- 文件 {path} ---\n" + _short(content)}
    except Exception as e:
        return {"observation": "", "error": f"read_file 失败：{e}"}


def write_file(workspace_path: str | None, path: str, content: str) -> dict:
    """在工作空间内写入或覆盖文件。"""
    try:
        target = _safe_path(workspace_path, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"observation": f"已写入文件：{path}（{len(content)} 字符）"}
    except Exception as e:
        return {"observation": "", "error": f"write_file 失败：{e}"}


def list_directory(workspace_path: str | None, path: str = "") -> dict:
    """列出工作空间内某个目录的文件和子目录。"""
    try:
        if not workspace_path:
            return {"observation": "", "error": "没有可用的工作空间，无法列出目录"}
        target = _safe_path(workspace_path, path) if path else Path(workspace_path).resolve()
        if not target.exists():
            return {"observation": f"目录不存在：{path}"}
        if not target.is_dir():
            return {"observation": f"路径不是目录：{path}"}
        all_entries = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        total = len(all_entries)
        dir_count = sum(1 for e in all_entries if e.is_dir())
        file_count = total - dir_count
        # 限制最多返回 100 条，避免输出过长撑爆 LLM 上下文导致卡住
        MAX_ENTRIES = 100
        entries = []
        for entry in all_entries[:MAX_ENTRIES]:
            prefix = "📁" if entry.is_dir() else "📄"
            size = f" {entry.stat().st_size} bytes" if entry.is_file() else ""
            entries.append(f"{prefix} {entry.name}{size}")
        header = f"--- 目录 {path or '.'}（共 {total} 项：{dir_count} 个目录，{file_count} 个文件）---"
        truncated = ""
        if total > MAX_ENTRIES:
            truncated = f"\n... 还有 {total - MAX_ENTRIES} 项未显示，请指定更具体的子路径查看"
        return {"observation": header + "\n" + "\n".join(entries) + truncated}
    except Exception as e:
        return {"observation": "", "error": f"list_directory 失败：{e}"}


def run_python_code(workspace_path: str | None, code: str) -> dict:
    """在独立子进程中执行 Python 代码片段，返回 stdout/stderr。"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            cwd=workspace_path or None,
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        result = ""
        if out:
            result += f"[stdout]\n{out}\n"
        if err:
            result += f"[stderr]\n{err}\n"
        if proc.returncode != 0:
            return {"observation": _short(result), "error": f"代码执行返回非零退出码 {proc.returncode}"}
        return {"observation": _short(result) or "（无输出）"}
    except subprocess.TimeoutExpired:
        return {"observation": "", "error": "代码执行超时（>15s）"}
    except Exception as e:
        return {"observation": "", "error": f"run_python_code 失败：{e}"}


def http_request(workspace_path: str | None, url: str, method: str = "GET", headers: str = "", body: str = "") -> dict:
    """发起 HTTP 请求。headers 为 JSON 字符串。"""
    try:
        req_headers: dict[str, str] = {}
        if headers:
            parsed = json.loads(headers)
            if isinstance(parsed, dict):
                req_headers = {str(k): str(v) for k, v in parsed.items()}
        req_headers.setdefault("User-Agent", "Mozilla/5.0 (taofei-agent)")
        # 中文等非 ASCII 字符需 URL 编码
        url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
        data_bytes = body.encode("utf-8") if body and method.upper() in ("POST", "PUT", "PATCH") else None
        req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
        try:
            parsed = json.loads(raw)
            body_out = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            body_out = raw
        return {"observation": f"HTTP {status}\n{_short(body_out)}"}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return {"observation": "", "error": f"HTTP {e.code}: {_short(raw)}"}
    except Exception as e:
        return {"observation": "", "error": f"http_request 失败：{e}"}


def ask_llm(llm_call: Callable[[list[dict]], str], prompt: str) -> dict:
    """让大模型做一个纯文本子任务，返回结果作为 observation。"""
    try:
        messages = [{"role": "user", "content": prompt}]
        reply = llm_call(messages)
        return {"observation": _short(reply)}
    except Exception as e:
        return {"observation": "", "error": f"ask_llm 失败：{e}"}


def call_skill(skill: dict, args: dict) -> dict:
    """调用技能管理里配置的 HTTP 技能（支持 {{input}} 占位替换）。

    skill 字段：id/name/url/method/headers(JSON)/body/description
    """
    try:
        name = skill.get("name") or skill.get("id") or "未命名技能"
        if skill.get("type") != "http":
            return {"observation": "", "error": f"技能「{name}」不是 HTTP 技能，无法直接调用"}
        inp = str(args.get("input", ""))
        url = str(skill.get("url", "")).replace("{{input}}", inp).strip()
        if not url:
            return {"observation": "", "error": f"HTTP 技能「{name}」未配置 URL"}
        # 中文等非 ASCII 字符需 URL 编码，否则 urllib 报 ascii 编码错误
        url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")

        method = str(skill.get("method", "GET")).upper()
        headers: dict[str, str] = {}
        raw_headers = str(skill.get("headers") or "").strip()
        if raw_headers:
            try:
                parsed = json.loads(raw_headers)
                if isinstance(parsed, dict):
                    headers = {str(k): str(v) for k, v in parsed.items() if str(v) != ""}
            except Exception:
                pass
        headers.setdefault("User-Agent", "Mozilla/5.0 (taofei-agent)")

        body = str(skill.get("body") or "").strip()
        data_bytes = None
        if method in ("POST", "PUT", "PATCH") and body:
            rendered = body.replace("{{input}}", inp)
            try:
                data_bytes = json.dumps(json.loads(rendered), ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            except Exception:
                data_bytes = rendered.encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed_body = json.loads(raw)
            # 若响应含 report 播报字段（如天气技能），直接返回该文案，便于 Agent 原样输出
            if isinstance(parsed_body, dict) and isinstance(parsed_body.get("report"), str):
                return {"observation": f"技能「{name}」响应 HTTP {status}\n{parsed_body['report']}"}
            body_out = json.dumps(parsed_body, ensure_ascii=False, indent=2)
        except Exception:
            body_out = raw
        return {"observation": f"技能「{name}」响应 HTTP {status}\n{_short(body_out)}"}
    except Exception as e:
        return {"observation": "", "error": f"call_skill 失败：{e}"}


# ------------------------------------------------------------------
# 工具注册表
# ------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "读取工作空间内指定文本文件的内容。参数 path 为相对路径。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于工作空间的文件路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "在工作空间内写入或覆盖文件。参数 path 为相对路径，content 为文件内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于工作空间的文件路径"},
                "content": {"type": "string", "description": "要写入的文件内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "列出工作空间内某个目录下的文件和子目录。path 为空字符串表示根目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于工作空间的目录路径，默认为空"},
            },
        },
    },
    {
        "name": "run_python_code",
        "description": "执行一段 Python 代码片段（15秒超时），用于计算、数据处理、运行脚本等。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python 代码字符串"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "http_request",
        "description": "发起 HTTP 请求，用于调用外部 API。headers 为 JSON 字符串。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "default": "GET"},
                "headers": {"type": "string", "description": "JSON 格式的请求头"},
                "body": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "ask_llm",
        "description": "当你需要模型帮你做总结、改写、分析等纯文本子任务时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "给模型的子任务提示词"},
            },
            "required": ["prompt"],
        },
    },
]


def build_skill_tools(skills: list[dict]) -> list[dict]:
    """把启用的 HTTP 技能转换为 Agent 可调用工具描述（call_skill_<id>）。"""
    tools: list[dict] = []
    for sk in skills or []:
        if sk.get("type") != "http" or not sk.get("enabled", True):
            continue
        sid = str(sk.get("id", ""))
        if not sid:
            continue
        name = sk.get("name") or sid
        desc = str(sk.get("description") or "").strip()
        url = str(sk.get("url") or "").strip()
        is_weather = "天气" in name or "weather" in url.lower()
        if desc and is_weather and "report" not in desc:
            desc = desc + "。工具响应中的 report 字段就是最终播报文案，请直接原样输出，不要改写。"
        tools.append({
            "name": f"call_skill_{sid}",
            "description": (
                f"调用技能「{name}」：{desc}".strip()
                + (f"。请求方式 {str(sk.get('method', 'GET')).upper()}，URL：{url}" if url else "")
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": f"传给技能「{name}」的输入/查询参数（可空）"},
                },
            },
        })
    return tools


def execute_tool(name: str, workspace_path: str | None, llm_call: Callable[[list[dict]], str], args: dict, skills: list[dict] | None = None) -> dict:
    """根据工具名分发执行。skills 提供动态注册的 HTTP 技能（call_skill_<id>）。"""
    if name == "read_file":
        return read_file(workspace_path, args.get("path", ""))
    if name == "write_file":
        return write_file(workspace_path, args.get("path", ""), args.get("content", ""))
    if name == "list_directory":
        return list_directory(workspace_path, args.get("path", ""))
    if name == "run_python_code":
        return run_python_code(workspace_path, args.get("code", ""))
    if name == "http_request":
        return http_request(
            workspace_path,
            args.get("url", ""),
            args.get("method", "GET"),
            args.get("headers", ""),
            args.get("body", ""),
        )
    if name == "ask_llm":
        return ask_llm(llm_call, args.get("prompt", ""))
    if name.startswith("call_skill_") and skills:
        sid = name[len("call_skill_"):]
        for sk in skills:
            if str(sk.get("id", "")) == sid:
                return call_skill(sk, args)
        return {"observation": "", "error": f"技能不存在：{sid}"}
    return {"observation": "", "error": f"未知工具：{name}"}
