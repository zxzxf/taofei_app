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
def read_file(workspace_path: str | None, path: str, offset: int = 1, limit: int = 200) -> dict:
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
        max_lines = min(1000, max(0, int(limit)))
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

        # 收集待扫描文件：path 可以是目录（递归遍历）或单个文件
        files_to_scan: list[str] = []
        if search_root.is_file():
            files_to_scan.append(str(search_root))
        else:
            for dirpath, dirnames, filenames in os.walk(search_root):
                # 过滤掉忽略的目录（原地修改 dirnames，os.walk 就不会进去）
                dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
                for fname in filenames:
                    files_to_scan.append(os.path.join(dirpath, fname))

        # 逐个文件扫描
        for full_path in files_to_scan:
            fname = os.path.basename(full_path)
            if not _is_code_file(fname):
                continue
            if include_exts:
                ext_ok = any(fname.lower().endswith(ext) for ext in include_exts)
                if not ext_ok:
                    continue

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


def _decode_bytes(raw: bytes | None) -> str:
    """智能解码子进程输出字节，优先 UTF-8，失败回退到 GBK。"""
    if not raw:
        return ""
    # 1. 优先 UTF-8
    try:
        text = raw.decode("utf-8")
        # 检查是否有大量乱码替换字符（说明实际上不是 UTF-8）
        if text.count("\ufffd") < len(text) * 0.05:
            return text.strip()
    except UnicodeDecodeError:
        pass
    # 2. 回退到 GBK（Windows 中文系统默认）
    try:
        return raw.decode("gbk", errors="replace").strip()
    except Exception:
        return raw.decode("utf-8", errors="replace").strip()


def _resolve_python_exe() -> str | None:
    """返回可用于执行代码的 Python 解释器路径。

    打包（PyInstaller）环境下 sys.executable 是应用本体（TaofeiAPI.exe），
    不能当解释器用——直接 spawn 会拉起一个全新后端实例（该实例还会自动打开
    浏览器），这是「会话中心说'分析项目'就弹出 http://127.0.0.1:800x/chat
    新建会话页面」的根源。此时按以下顺序查找真实 python：
      0) exe 邻近的应用自带环境（.venv / 同目录 python）——优先
      1) 系统 PATH
      2) 常见安装目录
      3) 注册表（PEP 514）
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    candidates: list[str] = []
    seen: set[str] = set()

    # 0) 应用自带 Python 环境：exe 同目录 / 上级目录 / 上上级目录（部署根）
    #    （Electron 打包结构：部署根\resources\backend\exe，.venv 在部署根）
    #    以及 exe 同目录的 python.exe（部分打包方案会随带解释器）。
    #    这类环境依赖完整、版本与应用匹配，优先级最高。
    exe_dir = Path(sys.executable).resolve().parent
    for base in (exe_dir, exe_dir.parent, exe_dir.parent.parent):
        p = base / ".venv" / "Scripts" / "python.exe"
        if p.is_file() and str(p) not in seen:
            seen.add(str(p))
            candidates.append(str(p))
    for p in (
        exe_dir / "python.exe",
        exe_dir / "python" / "python.exe",
    ):
        if p.is_file() and str(p) not in seen:
            seen.add(str(p))
            candidates.append(str(p))

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
        code = code if isinstance(code, str) else ""
        if not code.strip():
            return {"observation": "", "error": "代码为空，无法执行"}
        python_exe = _resolve_python_exe()
        if not python_exe:
            return {
                "observation": "",
                "error": "打包环境且系统未安装 Python，无法执行代码；请改用 read_file/list_directory 分析文件",
            }
        guard = (
            "import sys,types as _t;"
            "_w=_t.ModuleType('webbrowser');"
            "_w.open=lambda *a,**k:False;"
            "sys.modules['webbrowser']=_w;"
            "import os as _os;"
            "_os.startfile=lambda *a,**k:None\n"
        )
        safe_env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
        safe_env["TAOFEI_AGENT_CHILD"] = "1"
        safe_env["PYTHONIOENCODING"] = "utf-8"
        safe_env["PYTHONUTF8"] = "1"
        proc = subprocess.run(
            [python_exe, "-c", guard + code],
            capture_output=True,
            timeout=15,
            cwd=workspace_path or None,
            env=safe_env,
        )
        out = _decode_bytes(proc.stdout)
        err = _decode_bytes(proc.stderr)
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


def run_python_code_stream(workspace_path: str | None, code: str,
                           on_line=None) -> dict:
    """流式版本的 Python 代码执行：边执行边推送 stdout/stderr 行。

    Args:
        on_line: 可调用对象，接收 (stream_name, line_text)。
            stream_name: 'stdout' 或 'stderr'
    """
    try:
        code = code if isinstance(code, str) else ""
        if not code.strip():
            return {"observation": "", "error": "代码为空，无法执行"}
        python_exe = _resolve_python_exe()
        if not python_exe:
            return {
                "observation": "",
                "error": "打包环境且系统未安装 Python，无法执行代码；请改用 read_file/list_directory 分析文件",
            }
        guard = (
            "import sys,types as _t;"
            "_w=_t.ModuleType('webbrowser');"
            "_w.open=lambda *a,**k:False;"
            "sys.modules['webbrowser']=_w;"
            "import os as _os;"
            "_os.startfile=lambda *a,**k:None\n"
        )
        safe_env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
        safe_env["TAOFEI_AGENT_CHILD"] = "1"
        safe_env["PYTHONIOENCODING"] = "utf-8"
        safe_env["PYTHONUTF8"] = "1"
        # 注意：Windows 上不支持 select 管道，这里使用线程逐行读取
        proc = subprocess.Popen(
            [python_exe, "-c", guard + code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace_path or None,
            env=safe_env,
            bufsize=1,
            universal_newlines=True,
        )
        out_lines, err_lines = [], []
        done = {"stdout": False, "stderr": False}

        def _read_stream(stream, name, collector):
            for line in iter(stream.readline, ""):
                line = line.rstrip("\n")
                collector.append(line)
                if on_line:
                    try:
                        on_line(name, line)
                    except Exception:
                        pass
            done[name] = True

        import threading
        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, "stdout", out_lines), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, "stderr", err_lines), daemon=True)
        t_out.start()
        t_err.start()

        try:
            returncode = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            return {"observation": "", "error": "代码执行超时（>15s）"}

        t_out.join(timeout=5)
        t_err.join(timeout=5)

        out = "\n".join(out_lines)
        err = "\n".join(err_lines)
        result = ""
        if out:
            result += f"[stdout]\n{out}\n"
        if err:
            result += f"[stderr]\n{err}\n"
        if returncode != 0:
            return {"observation": _short(result), "error": f"代码执行返回非零退出码 {returncode}"}
        return {"observation": _short(result) or "（无输出）"}
    except Exception as e:
        return {"observation": "", "error": f"run_python_code_stream 失败：{e}"}


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
        "description": "读取工作空间内指定文本文件的内容，支持按行分页。offset 为起始行号（从 1 开始，默认 1），limit 为最多返回行数（默认 200，最大 1000）。文件较大时请用 offset 分页读取后半部分，例如 offset=500 读取第 500 行起的内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于工作空间的文件路径"},
                "offset": {"type": "integer", "description": "起始行号，从 1 开始，默认 1"},
                "limit": {"type": "integer", "description": "最多返回行数，默认 200，最大 1000"},
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
    {
        "name": "web_search",
        "description": "联网搜索互联网信息（DuckDuckGo，无需 key）。返回最多 max_results 条结果的标题/URL/摘要文本。适合查询最新资讯、文档、事实、代码示例等需要外部信息的问题。搜索失败会返回 Error 文本，可换关键词重试。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词（可含空格）"},
                "max_results": {"type": "integer", "description": "最多返回结果数，默认 5，最大 10"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_extract",
        "description": "抓取指定网页 URL 的内容并转为纯文本（自动剥离导航/脚本/样式）。适合读取文章正文、API 文档、新闻等。配合 web_search 使用：先搜索找到 URL，再抓取阅读。超过 max_chars 自动截断。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页完整 URL（https）"},
                "max_chars": {"type": "integer", "description": "最多返回字符数，默认 8000"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "create_skill",
        "description": "把本次任务中可复用的方法/流程沉淀为一个知识技能并保存（供未来对话参考）。当用户明确要求记住某流程，或你发现刚完成的步骤值得复用时应调用。name 用简短动词短语（如「部署 FastAPI 到服务器」），content 写完整可执行步骤。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能名，≤60 字，简短描述性"},
                "description": {"type": "string", "description": "一句话说明何时用此技能，≤300 字"},
                "content": {"type": "string", "description": "完整操作步骤/方法，≤8000 字"},
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "delegate_tasks",
        "description": "把多个相互独立的子问题拆给子代理并行执行（每个子代理有独立上下文并可调用工具），最后汇总。适合「对比/调研多个对象」「同时完成多件独立事项」。tasks 传每个子任务的一句话描述；结果会按传入顺序返回各子任务的结论。",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"request": {"type": "string", "description": "子任务的一句话描述，须自包含（子代理没有当前对话上下文）"}}, "required": ["request"]},
                    "description": "2-6 个独立子任务",
                },
            },
            "required": ["tasks"],
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


def execute_tool(name: str, workspace_path: str | None, llm_call: Callable[[list[dict]], str], args: dict, skills: list[dict] | None = None, tool_line_cb=None) -> dict:
    """根据工具名分发执行。skills 提供动态注册的 HTTP 技能（call_skill_<id>）。

    tool_line_cb: 可选，可调用对象 (stream_name, line) → None。
        仅对 run_python_code 等支持流式输出的工具生效，用于实时推送执行输出。
    """
    if not isinstance(args, dict):
        args = {}
    def _str(key, default=""):
        v = args.get(key, default)
        return v if isinstance(v, str) else default
    if name == "read_file":
        try:
            offset = int(args.get("offset", 1) or 1)
        except Exception:
            offset = 1
        try:
            limit = int(args.get("limit", 200) or 200)
        except Exception:
            limit = 200
        return read_file(workspace_path, _str("path"), offset=offset, limit=limit)
    if name == "grep_code":
        return grep_code(
            workspace_path,
            _str("pattern"),
            path=_str("path"),
            case_sensitive=bool(args.get("case_sensitive", False)),
            include=_str("include"),
        )
    if name == "write_file":
        return write_file(workspace_path, _str("path"), _str("content"))
    if name == "list_directory":
        return list_directory(workspace_path, _str("path"))
    if name == "run_python_code":
        if tool_line_cb:
            return run_python_code_stream(workspace_path, _str("code"), on_line=tool_line_cb)
        return run_python_code(workspace_path, _str("code"))
    if name == "http_request":
        return http_request(
            workspace_path,
            _str("url"),
            _str("method", "GET"),
            _str("headers"),
            _str("body"),
        )
    if name == "ask_llm":
        return ask_llm(llm_call, _str("prompt"))
    # ---- Hermes 能力补齐：联网 / 技能沉淀 / 子代理并行 ----
    if name == "web_search":
        from tools.web_search import search_web
        q = _str("query")
        try:
            n = max(1, min(int(args.get("max_results", 5) or 5), 10))
        except Exception:
            n = 5
        text = search_web(q, max_results=n) if q else "Error: query 不能为空"
        if text.startswith("Error:"):
            return {"observation": "", "error": text}
        return {"observation": text, "error": ""}
    if name == "web_extract":
        from tools.web_extract import extract_web
        url = _str("url")
        try:
            mc = max(1000, min(int(args.get("max_chars", 8000) or 8000), 50000))
        except Exception:
            mc = 8000
        text = extract_web(url, max_chars=mc) if url else "Error: url 不能为空"
        if text.startswith("Error:"):
            return {"observation": "", "error": text}
        return {"observation": text, "error": ""}
    if name == "create_skill":
        from skills_lifecycle import create_skill
        res = create_skill(_str("name"), description=_str("description"),
                           content=_str("content"), source="auto")
        if res.get("ok"):
            return {"observation": f"技能「{res.get('name')}」已保存（id={res.get('id')}），"
                                  "未来相关任务可参考该技能。"}
        return {"observation": "", "error": str(res.get("error", "技能保存失败"))}
    if name == "delegate_tasks":
        from agent.delegator import delegate_tasks
        raw_tasks = args.get("tasks") or []
        specs = []
        for i, tk in enumerate(raw_tasks):
            req = (tk.get("request") if isinstance(tk, dict) else str(tk)).strip()
            if req:
                specs.append({"id": f"sub{i + 1}", "request": req})
        if not specs:
            return {"observation": "", "error": "delegate_tasks: tasks 为空或格式错误"}
        # 子代理可用工具 = 内置 + 当前绑定的 HTTP 技能
        sub_schemas = tools_to_openai_functions(TOOLS + build_skill_tools(skills or []))
        result = delegate_tasks(
            specs,
            llm_call=llm_call,
            tool_schemas=sub_schemas,
            execute_tool=execute_tool,
            workspace_path=workspace_path,
        )
        lines = []
        for r in result.get("results", []):
            if r["status"] == "completed":
                lines.append(f"子任务 {r['id']}（{r['duration_ms']}ms）：{r['answer']}")
            else:
                lines.append(f"子任务 {r['id']}：失败 - {r.get('error')}")
        return {"observation": "\n\n".join(lines), "error": ""}
    if name.startswith("call_skill_") and skills:
        sid = name[len("call_skill_"):]
        for sk in skills:
            if str(sk.get("id", "")) == sid:
                return call_skill(sk, args)
        return {"observation": "", "error": f"技能不存在：{sid}"}
    return {"observation": "", "error": f"未知工具：{name}"}


# ------------------------------------------------------------------
# Function Calling 模式支持
# ------------------------------------------------------------------

def tools_to_openai_functions(tool_list: list[dict]) -> list[dict]:
    """把 TOOLS 格式转为 OpenAI function calling 格式。

    输入格式：[{name, description, parameters: {type, properties, required}}]
    输出格式：[{"type": "function", "function": {name, description, parameters}}]
    """
    result = []
    for t in tool_list:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return result


def execute_tool_fc(
    name: str,
    workspace_path: str | None,
    llm_call: Callable[[list[dict]], str],
    args: dict,
    skills: list[dict] | None = None,
    tool_line_cb=None,
) -> str:
    """function calling 版本的工具执行：直接返回 observation 字符串。

    出错时返回 "Error: ..." 格式字符串，模型可以直接看到错误并重试。
    tool_line_cb: 可选，流式输出回调 (stream_name, line) → None
    """
    result = execute_tool(name, workspace_path, llm_call, args, skills=skills,
                          tool_line_cb=tool_line_cb)
    obs = result.get("observation", "")
    err = result.get("error", "")
    if err:
        msg = f"Error: {err}\n{obs}".strip()
    else:
        msg = obs or "（无输出）"
    # 兜底截断（任务 9.2）：任何工具结果回传 LLM / 存入会话前
    # 统一限制在 MAX_OUTPUT_LEN 内，防超大输出撑爆上下文。
    # 已在工具内部截断的短结果原样返回，无额外开销。
    return _short(msg, MAX_OUTPUT_LEN)
