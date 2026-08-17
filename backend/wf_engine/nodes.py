"""节点执行器：start / llm / http / ifelse / code / end / template。

每个执行器签名统一：
    execute(node: dict, pool: VariablePool, ctx: dict) -> dict

ctx 由引擎注入：
    ctx["llm_call"]      callable(messages: list[dict]) -> str   大模型调用
    ctx["log"]           callable(level, message) -> None        节点内日志
    ctx["python_bin"]    str                                     code 节点用的解释器
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

from .variable_pool import VariablePool

MAX_LOG_LEN = 300


def _short(text: Any, n: int = MAX_LOG_LEN) -> str:
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


# ---------------- start ----------------
def exec_start(node: dict, pool: VariablePool, ctx: dict) -> dict:
    """开始节点：把声明的输入变量写入自身输出（inputs 已由引擎预置到 sys）。"""
    data = node.get("data", {})
    out: dict[str, Any] = {}
    for var in data.get("variables", []):
        name = var.get("variable") or var.get("name") or ""
        if name:
            out[name] = pool.get(f"sys.{name}", "")
    return out


# ---------------- llm ----------------
def exec_llm(node: dict, pool: VariablePool, ctx: dict) -> dict:
    data = node.get("data", {})
    system_prompt = data.get("system_prompt", "")
    prompt = data.get("prompt", "")
    if isinstance(prompt, list):  # Dify 兼容：prompt_template 数组
        prompt = "\n\n".join(
            f"[{p.get('role', 'user')}]\n{p.get('text', '')}" for p in prompt if isinstance(p, dict)
        )
    prompt = str(pool.render(prompt)) if prompt else ""
    if not prompt:
        raise ValueError("LLM 节点未配置提示词（prompt）")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": str(pool.render(system_prompt))})
    messages.append({"role": "user", "content": prompt})

    ctx["log"]("INFO", f"LLM 节点调用模型，提示词 {len(prompt)} 字")
    reply = ctx["llm_call"](messages)
    reply = str(reply)
    ctx["log"]("INFO", f"LLM 节点返回 {len(reply)} 字：{_short(reply)}")
    return {"text": reply}


# ---------------- http ----------------
def exec_http(node: dict, pool: VariablePool, ctx: dict) -> dict:
    import urllib.error
    import urllib.request

    data = node.get("data", {})
    method = str(data.get("method", "GET")).upper()
    url = str(pool.render(data.get("url", "")))
    if not url:
        raise ValueError("HTTP 节点未配置 URL")
    headers = pool.render_obj(data.get("headers") or {})
    if not isinstance(headers, dict):
        headers = {}
    headers = {str(k): str(v) for k, v in headers.items() if str(v) != ""}
    headers.setdefault("User-Agent", "Mozilla/5.0 (taofei-workflow)")
    body = data.get("body", "")
    if isinstance(body, (dict, list)):
        body = json.dumps(pool.render_obj(body), ensure_ascii=False)
    elif body:
        body = str(pool.render(body))

    ctx["log"]("INFO", f"HTTP 节点请求 {method} {url}")
    req = urllib.request.Request(url, data=(body.encode("utf-8") if body and method in ("POST", "PUT", "PATCH") else None), headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = raw
    ctx["log"]("INFO", f"HTTP 节点响应 {status}：{_short(parsed)}")
    return {"status": status, "body": parsed}


# ---------------- ifelse ----------------
_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "contains": lambda a, b: str(b) in str(a),
    "not contains": lambda a, b: str(b) not in str(a),
    "start with": lambda a, b: str(a).startswith(str(b)),
    "end with": lambda a, b: str(a).endswith(str(b)),
    "is": lambda a, b: str(a) == str(b),
    "is not": lambda a, b: str(a) != str(b),
    "empty": lambda a, b: a is None or str(a) == "",
    "not empty": lambda a, b: not (a is None or str(a) == ""),
    ">": lambda a, b: float(a) > float(b),
    ">=": lambda a, b: float(a) >= float(b),
    "<": lambda a, b: float(a) < float(b),
    "<=": lambda a, b: float(a) <= float(b),
}


def exec_ifelse(node: dict, pool: VariablePool, ctx: dict) -> dict:
    data = node.get("data", {})
    conditions = data.get("conditions", [])
    logical = str(data.get("logical_operator", "and")).lower()
    if not conditions:
        raise ValueError("条件分支节点未配置条件")

    results: list[bool] = []
    for cond in conditions:
        var_path = cond.get("variable", "")
        actual = pool.get(var_path)
        op = str(cond.get("operator", "contains")).lower()
        expected = pool.render(cond.get("value", ""))
        fn = _OPERATORS.get(op)
        if fn is None:
            raise ValueError(f"不支持的条件运算符：{op}")
        try:
            ok = fn(actual, expected)
        except (TypeError, ValueError):
            ok = False
        results.append(ok)
        ctx["log"]("INFO", f"条件判断 {var_path}({actual!r}) {op} {expected!r} -> {ok}")

    branch = all(results) if logical != "or" else any(results)
    ctx["log"]("INFO", f"条件分支走向：{branch}")
    return {"result": "true" if branch else "false"}


# ---------------- code ----------------
def exec_code(node: dict, pool: VariablePool, ctx: dict) -> dict:
    data = node.get("data", {})
    code = data.get("code", "")
    if not code:
        raise ValueError("代码节点未配置代码")
    variables = pool.render_obj(data.get("variables", {}))
    payload = json.dumps({"variables": variables if isinstance(variables, dict) else {}}, ensure_ascii=False)

    ctx["log"]("INFO", f"代码节点执行（{len(code)} 字符，变量：{list(variables) if isinstance(variables, dict) else []}）")
    python_bin = ctx.get("python_bin") or "python"
    try:
        proc = subprocess.run(
            [python_bin, "-c", code],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=int(data.get("timeout", 15)),
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"代码节点执行超时（>{data.get('timeout', 15)}s）")
    if proc.returncode != 0:
        err = (proc.stderr or "")[-MAX_LOG_LEN:]
        raise ValueError(f"代码节点执行失败：{err}")
    stdout = proc.stdout.strip()
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = {"text": stdout}
        if not isinstance(parsed, dict):
            parsed = {"result": parsed}
    else:
        parsed = {}
    ctx["log"]("INFO", f"代码节点输出：{_short(parsed)}")
    return parsed


# ---------------- skill（调用技能管理中配置的技能） ----------------
def exec_skill(node: dict, pool: VariablePool, ctx: dict) -> dict:
    """技能节点：直接把集成管理里的技能挂到画布上执行。

    node.data:
        skill_id  str  技能 id（skills.json 中的 id）
        input     str  输入内容，支持 {{#节点.字段#}} 模板；HTTP 技能的 url/body/headers 中可用 {{input}} 引用

    ctx 需注入：
        get_skill  callable(skill_id: str) -> dict | None   由 main.py 提供技能查找
    """
    data = node.get("data", {})
    skill_id = str(data.get("skill_id", ""))
    get_skill = ctx.get("get_skill")
    skill = get_skill(skill_id) if get_skill else None
    if not skill:
        raise ValueError(f"技能节点未选择技能，或技能不存在（id={skill_id or '空'}）")
    if not skill.get("enabled", True):
        raise ValueError(f"技能「{skill.get('name')}」已被禁用，请到集成管理启用")
    inp = str(pool.render(data.get("input", "")))
    name = skill.get("name", skill_id)

    # Claude 技能：SKILL.md 指令作为 system，input 作为 user，交给大模型
    if skill.get("type") == "claude":
        messages = [
            {"role": "system", "content": str(skill.get("instructions", ""))},
            {"role": "user", "content": inp},
        ]
        ctx["log"]("INFO", f"技能节点调用 Claude 技能「{name}」，输入 {len(inp)} 字")
        reply = str(ctx["llm_call"](messages))
        ctx["log"]("INFO", f"技能节点「{name}」返回 {len(reply)} 字：{_short(reply)}")
        return {"text": reply}

    # HTTP 技能：渲染 url/headers/body（支持 {{#...#}} 与 {{input}}）
    import urllib.error
    import urllib.request

    def _tpl(text: str) -> str:
        return str(pool.render(str(text))).replace("{{input}}", inp)

    method = str(skill.get("method", "GET")).upper()
    url = _tpl(skill.get("url", ""))
    if not url:
        raise ValueError(f"HTTP 技能「{name}」未配置 URL")
    headers: dict[str, str] = {}
    raw_headers = str(skill.get("headers") or "").strip()
    if raw_headers:
        try:
            parsed = json.loads(_tpl(raw_headers))
            if isinstance(parsed, dict):
                headers = {str(k): str(v) for k, v in parsed.items() if str(v) != ""}
        except Exception:
            ctx["log"]("WARN", f"HTTP 技能「{name}」headers 非法 JSON，已忽略")
    headers.setdefault("User-Agent", "Mozilla/5.0 (taofei-workflow)")
    body = str(skill.get("body") or "").strip()
    data_bytes = None
    if method in ("POST", "PUT", "PATCH") and body:
        rendered = _tpl(body)
        try:  # 优先按 JSON 发送（渲染后的模板值）
            data_bytes = json.dumps(json.loads(rendered), ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        except Exception:
            data_bytes = rendered.encode("utf-8")

    ctx["log"]("INFO", f"技能节点调用 HTTP 技能「{name}」：{method} {url}")
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
    except Exception:
        parsed_body = raw
    ctx["log"]("INFO", f"技能节点「{name}」响应 {status}：{_short(parsed_body)}")
    return {"status": status, "body": parsed_body}


# ---------------- template（文本拼接） ----------------
def exec_template(node: dict, pool: VariablePool, ctx: dict) -> dict:
    data = node.get("data", {})
    text = str(pool.render(data.get("template", "")))
    ctx["log"]("INFO", f"模板节点输出：{_short(text)}")
    return {"text": text}


# ---------------- end ----------------
def exec_end(node: dict, pool: VariablePool, ctx: dict) -> dict:
    data = node.get("data", {})
    out: dict[str, Any] = {}
    for item in data.get("outputs", []):
        name = item.get("name") or item.get("variable") or ""
        if not name:
            continue
        selector = item.get("value", item.get("value_selector", ""))
        if isinstance(selector, list):  # Dify 兼容：value_selector 是路径数组
            selector = ".".join(str(s) for s in selector)
        out[name] = pool.render(selector)
    return out


NODE_EXECUTORS = {
    "start": exec_start,
    "llm": exec_llm,
    "http": exec_http,
    "http-request": exec_http,   # Dify 节点类型名
    "skill": exec_skill,         # 技能节点（调用集成管理中配置的技能）
    "ifelse": exec_ifelse,
    "if-else": exec_ifelse,      # Dify 节点类型名
    "code": exec_code,
    "template": exec_template,
    "template-transform": exec_template,
    "end": exec_end,
    "answer": exec_end,          # Dify chatflow 的 answer 节点近似处理
}


def get_executor(node_type: str):
    return NODE_EXECUTORS.get(node_type)
