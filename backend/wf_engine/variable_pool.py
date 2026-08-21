"""变量池：工作流全局共享状态，支持 {{#node_id.field#}} 模板引用渲染。

约定（与 Dify DSL 对齐）：
- {{#sys.query#}}       引用运行时主输入
- {{#start_1.query#}}   引用开始节点定义的输入变量
- {{#llm_1.text#}}      引用某节点的输出字段
"""
from __future__ import annotations

import re
import threading
from typing import Any

_REF_RE = re.compile(r"\{\{#\s*([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_]+)*)\s*#\}\}")


class VariablePool:
    def __init__(self, inputs: dict[str, Any] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {"sys": dict(inputs or {})}
        self._lock = threading.Lock()  # 并行节点同时写各自输出时保护

    # ---------- 读写 ----------
    def set(self, node_id: str, outputs: dict[str, Any]) -> None:
        with self._lock:
            if node_id == "sys":
                self._store["sys"].update(outputs)
                return
            cur = self._store.setdefault(node_id, {})
            cur.update(outputs)

    def get(self, path: str, default: Any = None) -> Any:
        parts = path.split(".")
        node_id, fields = parts[0], parts[1:]
        node = self._store.get(node_id)
        if node is None:
            return default
        val: Any = node
        for f in fields:
            if isinstance(val, dict):
                val = val.get(f)
            else:
                return default
        return val

    # ---------- 渲染 ----------
    def render(self, text: Any) -> Any:
        """渲染模板字符串。若整串就是单个引用且值为非字符串对象，直接返回原对象。"""
        if not isinstance(text, str):
            return text
        whole = _REF_RE.fullmatch(text.strip())
        if whole:
            val = self.get(whole.group(1))
            if val is not None and not isinstance(val, str):
                return val
        def _sub(m: re.Match) -> str:
            val = self.get(m.group(1))
            if val is None:
                return ""
            return val if isinstance(val, str) else _to_str(val)
        return _REF_RE.sub(_sub, text)

    def render_obj(self, obj: Any) -> Any:
        """递归渲染 dict / list / str 中的模板引用。"""
        if isinstance(obj, str):
            return self.render(obj)
        if isinstance(obj, dict):
            return {k: self.render_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.render_obj(v) for v in obj]
        return obj


def _to_str(val: Any) -> str:
    import json

    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)
