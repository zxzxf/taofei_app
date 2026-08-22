"""Agent 工具集：供 ReAct 循环调用的本地工具。

每个工具都是一个普通函数，签名统一为：
    tool_name(workspace_path: str | None, **kwargs) -> dict
返回字典必须包含 "observation" 键（字符串），可选 "error" 键表示失败。
"""

from __future__ import annotations

import json
import os
import shutil
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
def read_file(workspace_path: str | None, path: str, offset: int = 1, limit: int = 100) -> dict:
    """读取工作空间内指定文本文件的内容，支持按行分页。

    offset 为起始行号（从 1 开始），limit 为最多返回行数。
    大文件请配合 offset 分页查看后半部分，例如 offset=500 读取第 500 行起的内容。
    """
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
        lines = content.splitlines()
        total = len(lines)
        start = max(1, int(offset))
        max_lines = min(500, max(0, int(limit)))
        if start > total:
            return {"observation": f"文件 {path} 共 {total} 行，起始行 {offset} 超出范围"}
        stop = min(total, start + max_lines - 1) if max_lines > 0 else total
        chunk = lines[start - 1 : stop]
        numbered = [f"{start + i}: {ln[:200]}" for i, ln in enumerate(chunk)]
        note = ""
        if stop < total:
            note = f"\n... 还有 {total - stop} 行未显示，可传 offset={stop + 1} 继续读取"
        header = f"--- 文件 {path}（第 {start}-{stop} 行 / 共 {total} 行）---"
        return {"observation": header + "\n" + "\n".join(numbered) + note}
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


def _is_ignored_dir(name: str) -> bool:
    """判断目录是否应跳过搜索。"""
    IGNORED_DIRS = {
        "node_modules", ".git", "build", "dist", "__pycache__",
        ".venv", "venv", "env", ".next", ".nuxt", ".cache",
        ".idea", ".vscode", "target", "out", "assets", "static",
        "public", "coverage", ".output",
    }
    return name.lower() in IGNORED_DIRS or name.startswith(".")


def _is_code_file(name: str) -> bool:
    """判断是否为需要搜索的代码/文本文件。"""
    CODE_EXTS = {
        ".vue", ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".c", ".cpp",
        ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
        ".css", ".scss", ".less", ".html", ".htm", ".xml", ".json", ".yaml",
        ".yml", ".md", ".markdown", ".txt", ".sh", ".bash", ".sql",
    }
    return any(name.lower().endswith(ext) for ext in CODE_EXTS)


def grep_code(
    workspace_path: str | None,
    pattern: str,
    path: str = "",
    case_sensitive: bool = False,
    include: str = "",
) -> dict:
    """在工作空间内全局搜索关键词（类似 IDE 的全局查找）。

    pattern 为搜索关键词，支持普通字符串匹配。
    path 可选，用于缩小搜索范围到某个子目录。
    case_sensitive 控制是否大小写敏感，默认不敏感。
    include 可选，逗号分隔的文件后缀过滤，如 "*.vue,*.js"。
    自动跳过 node_modules、.git、build 等大目录。
    """
    try:
        if not workspace_path:
            return {"observation": "", "error": "没有可用的工作空间，无法搜索"}
        root = Path(workspace_path).resolve()
        search_root = (root / path).resolve() if path else root
        # 确保搜索范围在 workspace 内
        try:
            search_root.relative_to(root)
        except ValueError:
            return {"observation": "", "error": f"路径越界：{path}"}
        if not search_root.exists():
            return {"observation": f"搜索路径不存在：{path or '.'}"}

        if not pattern:
            return {"observation": "", "error": "搜索关键词不能为空"}

        # 解析 include 过滤
        include_exts: set[str] = set()
        if include:
            for item in include.split(","):
                item = item.strip().lower()
                if not item:
                    continue
                if item.startswith("*."):
                    include_exts.add(item[1:])
                elif item.startswith("."):
                    include_exts.add(item)
                else:
                    include_exts.add("." + item)

        # 准备匹配
        search_pattern = pattern if case_sensitive else pattern.lower()
        results: list[tuple[str, int, str]] = []  # (file_path, line_no, line_content)
        file_count = 0
        total_matches = 0
        MAX_MATCHES = 200  # 最多匹配数，防止过多

        # 遍历文件
        for dirpath, dirnames, filenames in os.walk(search_root):
            # 过滤掉忽略的目录（原地修改 dirnames，os.walk 就不会进去）
            dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]

            for fname in filenames:
                if not _is_code_file(fname):
                    continue
                if include_exts:
                    ext_ok = any(fname.lower().endswith(ext) for ext in include_exts)
                    if not ext_ok:
                        continue

                full_path = os.path.join(dirpath, fname)
                # 跳过符号链接和过大的文件
                try:
                    if os.path.islink(full_path):
                        continue
                    size = os.path.getsize(full_path)
                    if size > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                except OSError:
                    continue

                file_matched = False
                for line_idx, line in enumerate(lines):
                    line_stripped = line.rstrip("\n").rstrip("\r")
                    haystack = line_stripped if case_sensitive else line_stripped.lower()
                    if search_pattern in haystack:
                        # 计算相对路径
                        rel_path = os.path.relpath(full_path, root)
                        results.append((rel_path, line_idx + 1, line_stripped.strip()))
                        total_matches += 1
                        file_matched = True
                        if total_matches >= MAX_MATCHES:
                            break
                if file_matched:
                    file_count += 1
                if total_matches >= MAX_MATCHES:
                    break
            if total_matches >= MAX_MATCHES:
                break

        # 按文件分组输出
        if not results:
            scope = path or "整个工作空间"
            return {"observation": f"未找到匹配「{pattern}」的内容（搜索范围：{scope}）"}

        # 聚合：按文件分组
        from collections import defaultdict
        by_file: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for fpath, lno, lcontent in results:
            by_file[fpath].append((lno, lcontent))

        lines_out = []
        scope_note = f"（搜索范围：{path}）" if path else ""
        header = f"--- 搜索结果：「{pattern}」{scope_note}共 {file_count} 个文件，{total_matches} 处匹配 ---"
        lines_out.append(header)

        MAX_PER_FILE = 10  # 每文件最多显示匹配行数
        shown_files = 0
        for fpath in sorted(by_file.keys()):
            matches = by_file[fpath]
            lines_out.append("")
            lines_out.append(f"📄 {fpath}")
            shown_files += 1
            for lno, lcontent in matches[:MAX_PER_FILE]:
                # 截断过长的行
                display = lcontent[:200] if len(lcontent) > 200 else lcontent
                lines_out.append(f"  {lno}: {display}")
            if len(matches) > MAX_PER_FILE:
                lines_out.append(f"  ... 还有 {len(matches) - MAX_PER_FILE} 处匹配")

        truncated_note = ""
        if total_matches >= MAX_MATCHES:
            truncated_note = f"\n\n⚠️ 结果已达上限（{MAX_MATCHES} 处），可能还有更多匹配。请缩小搜索范围或使用更精确的关键词。"

        output = "\n".join(lines_out) + truncated_note
        return {"observation": _short(output, MAX_OUTPUT_LEN)}

    except Exception as e:
        return {"observation": "", "error": f"grep_code 失败：{e}"}


def _is_usable_python(path: str) -> bool:
    """真实执行一次验证解释器可用，排除不可用的候选。

    重点排除 Microsoft Store 的「应用执行别名」（%LOCALAPPDATA%\\Microsoft\\WindowsApps\\
    python.exe）：该类别名在本机未安装 Store 版 Python 时存在但无法执行，
    subprocess 运行会返回 9009（命令未找到），导致 Agent 报
    「代码执行返回非零退出码 9009」。
    """
    try:
        if os.path.isdir(path):
            return False
        norm = os.path.normpath(path).lower()
        if "windowsapps" in norm.split(os.sep):
            return False
        proc = subprocess.run(
            [path, "-c", "import sys"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _resolve_python_exe() -> str | None:
    """返回可用于执行代码的 Python 解释器路径。

    打包（PyInstaller）环境下 sys.executable 是应用本体（CrewAIWorkbench.exe），
    不能当解释器用——直接 spawn 会拉起一个全新后端实例（该实例还会自动打开
    浏览器），这是「会话中心说'分析项目'就弹出 http://127.0.0.1:800x/chat
    新建会话页面」的根源。此时改为在系统 PATH 及常见安装目录中查找真实的 python。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    candidates: list[str] = []
    seen: set[str] = set()

    # 1) PATH 中的候选
    for name in ("python.exe", "python3.exe", "python", "python3", "py"):
        p = shutil.which(name)
        if p and p not in seen:
            seen.add(p)
            candidates.append(p)

    # which 只返回 PATH 中的第一个匹配；手动遍历 PATH，避免第一个命中
    # WindowsApps 别名后漏掉后面真实的 python。
    for name in ("python.exe", "python3.exe"):
        for dir_ in os.environ.get("PATH", "").split(os.pathsep):
            if not dir_:
                continue
            p = os.path.join(dir_, name)
            if p not in seen:
                seen.add(p)
                candidates.append(p)

    # 2) 扫描常见 Python 安装目录（Windows 常见位置）
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "C:\\Users\\" + user + "\\AppData\\Local")

    common_dirs: list[str] = []
    for major in (3,):
        for minor in range(13, 6, -1):  # 3.13 -> 3.7
            common_dirs.append(rf"C:\Python{major}{minor}")
            common_dirs.append(rf"C:\Python{major}{minor}-32")
            common_dirs.append(rf"C:\Python{major}{minor}-64")
            common_dirs.append(os.path.join(program_files, rf"Python{major}{minor}"))
            common_dirs.append(os.path.join(program_files_x86, rf"Python{major}{minor}"))
            common_dirs.append(os.path.join(local_appdata, rf"Programs\Python\Python{major}{minor}"))
            common_dirs.append(rf"C:\Users\{user}\AppData\Local\Programs\Python\Python{major}{minor}")

    for d in common_dirs:
        if not d:
            continue
        for name in ("python.exe", "python3.exe"):
            p = os.path.join(d, name)
            if p not in seen:
                seen.add(p)
                candidates.append(p)

    # 3) 使用注册表查找 Windows 上通过官方安装程序安装的 Python（PEP 514）
    if sys.platform == "win32":
        try:
            import winreg

            def _enum_reg(root: int, key_path: str) -> None:
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                sub_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, sub_name) as sub_key:
                                    install_path, _ = winreg.QueryValueEx(sub_key, "ExecutablePath")
                                    if install_path and os.path.isfile(install_path) and install_path not in seen:
                                        seen.add(install_path)
                                        candidates.append(install_path)
                            except OSError:
                                continue
                except OSError:
                    return

            _enum_reg(winreg.HKEY_CURRENT_USER, r"Software\Python\PythonCore")
            _enum_reg(winreg.HKEY_LOCAL_MACHINE, r"Software\Python\PythonCore")
            _enum_reg(winreg.HKEY_LOCAL_MACHINE, r"Software\Wow6432Node\Python\PythonCore")
        except Exception:
            pass

    for cand in candidates:
        if _is_usable_python(cand):
            return cand
    return None


def run_python_code(workspace_path: str | None, code: str) -> dict:
    """在独立子进程中执行 Python 代码片段，返回 stdout/stderr。"""
    try:
        python_exe = _resolve_python_exe()
        if not python_exe:
            return {
                "observation": "",
                "error": "打包环境且系统未安装 Python，无法执行代码；请改用 read_file/list_directory 分析文件",
            }
        # 安全护栏：Agent 代码不允许打开浏览器或拉起会自动开浏览器的后端
        # 1) 预置 webbrowser 空实现（import webbrowser 后 open() 无副作用）
        # 2) 预置 os.startfile 空实现（防止用系统默认程序打开 URL）
        # 3) 注入 TAOFEI_AGENT_CHILD=1，backend/main.py 据此跳过启动时自动开浏览器
        guard = (
            "import sys,types as _t;"
            "_w=_t.ModuleType('webbrowser');"
            "_w.open=lambda *a,**k:False;"
            "sys.modules['webbrowser']=_w;"
            "import os as _os;"
            "_os.startfile=lambda *a,**k:None\n"
        )
        env = {**os.environ, "TAOFEI_AGENT_CHILD": "1"}
        proc = subprocess.run(
            [python_exe, "-c", guard + code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            cwd=workspace_path or None,
            env=env,
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
        "description": "读取工作空间内指定文本文件的内容，支持按行分页。offset 为起始行号（从 1 开始，默认 1），limit 为最多返回行数（默认 100，最大 500）。文件较大时请用 offset 分页读取后半部分，例如 offset=500 读取第 500 行起的内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于工作空间的文件路径"},
                "offset": {"type": "integer", "description": "起始行号，从 1 开始，默认 1"},
                "limit": {"type": "integer", "description": "最多返回行数，默认 100，最大 500"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep_code",
        "description": "在工作空间内全局搜索关键词（类似 IDE 全局查找），一步找到包含关键词的文件和行号。自动跳过 node_modules、.git、build 等大目录。搜索代码、配置、按钮文字等都优先用这个工具，比逐个 list_directory + read_file 快很多。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "要搜索的关键词"},
                "path": {"type": "string", "description": "可选，缩小搜索范围到某个子目录"},
                "case_sensitive": {"type": "boolean", "description": "是否大小写敏感，默认 false"},
                "include": {"type": "string", "description": "可选，逗号分隔的文件后缀过滤，如 *.vue,*.js"},
            },
            "required": ["pattern"],
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
        try:
            offset = int(args.get("offset", 1))
        except Exception:
            offset = 1
        try:
            limit = int(args.get("limit", 100))
        except Exception:
            limit = 100
        return read_file(workspace_path, args.get("path", ""), offset=offset, limit=limit)
    if name == "grep_code":
        return grep_code(
            workspace_path,
            args.get("pattern", ""),
            path=args.get("path", ""),
            case_sensitive=bool(args.get("case_sensitive", False)),
            include=args.get("include", ""),
        )
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
