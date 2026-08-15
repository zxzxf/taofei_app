"""Dify DSL（YAML）导入转换：把 Dify 导出的应用 YAML 转为本平台工作流图。

用法：
    graph = convert_dify_dsl(yaml_text)   # 抛 ValueError 时带原因说明

支持节点：start / llm / http-request / if-else / code / template-transform / end / answer
不支持的节点会被跳过并在 warnings 中提示。
"""
from __future__ import annotations

from typing import Any

import yaml

SUPPORTED = {"start", "llm", "http-request", "if-else", "code", "template-transform", "end", "answer"}


def convert_dify_dsl(text: str) -> tuple[dict, list[str]]:
    """返回 (graph, warnings)。"""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败：{exc}")
    if not isinstance(data, dict):
        raise ValueError("DSL 内容不是有效的 Dify 应用导出")

    graph_data = data.get("workflow") or data.get("graph") or {}
    graph = graph_data.get("graph") if isinstance(graph_data.get("graph"), dict) else graph_data
    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])
    warnings: list[str] = []

    nodes: list[dict] = []
    for n in raw_nodes:
        if not isinstance(n, dict):
            continue
        data_ = n.get("data", {}) or {}
        ntype = str(data_.get("type") or n.get("type") or "")
        if ntype not in SUPPORTED:
            warnings.append(f"跳过不支持的节点类型「{ntype}」（{data_.get('title', n.get('id'))}）")
            continue
        pos = n.get("position", {}) or {}
        node = {
            "id": str(n.get("id")),
            "type": ntype,
            "position": {"x": pos.get("x", 0), "y": pos.get("y", 0)},
            "data": _convert_data(ntype, data_),
        }
        nodes.append(node)

    # 记录被保留的节点 id，过滤悬空边
    kept = {str(n["id"]) for n in nodes}
    edges = [
        {"id": str(e.get("id") or f"e_{i}"), "source": str(e.get("source")), "target": str(e.get("target")),
         "sourceHandle": e.get("sourceHandle")}
        for i, e in enumerate(raw_edges)
        if isinstance(e, dict) and str(e.get("source")) in kept and str(e.get("target")) in kept
    ]
    if not nodes:
        raise ValueError("DSL 中没有可转换的节点")
    return {"nodes": nodes, "edges": edges}, warnings


def _convert_data(ntype: str, d: dict) -> dict:
    out: dict[str, Any] = {"title": d.get("title", ntype)}
    if ntype == "start":
        out["variables"] = [
            {"variable": v.get("variable", ""), "label": v.get("label", v.get("variable", "")), "required": bool(v.get("required", True))}
            for v in (d.get("variables") or []) if isinstance(v, dict)
        ]
    elif ntype == "llm":
        out["system_prompt"] = d.get("sys_prompt", "") or ""
        pt = d.get("prompt_template")
        if isinstance(pt, list):
            out["prompt"] = "\n\n".join(
                str(p.get("text", "")) for p in pt if isinstance(p, dict)
            ).strip()
        else:
            out["prompt"] = str(d.get("prompt", "") or "")
        out["model"] = (d.get("model") or {}).get("name", "") if isinstance(d.get("model"), dict) else ""
    elif ntype == "http-request":
        out["method"] = str(d.get("method", "GET")).upper()
        out["url"] = str(d.get("url", "") or "")
        out["headers"] = _kv_pairs(d.get("headers"))
        body = d.get("body")
        out["body"] = body if isinstance(body, (str, dict)) else ""
        if d.get("authorization") and d.get("authorization", {}).get("type") != "no-auth":
            warnings_auth = d.get("authorization", {})
            out.setdefault("headers", {})
    elif ntype == "if-else":
        # Dify 新版是 cases 数组，只取第一组
        cases = d.get("cases") or []
        conds = []
        logical = d.get("logical_operator", "and")
        if cases:
            case = cases[0] if isinstance(cases[0], dict) else {}
            logical = case.get("logical_operator", "and")
            for c in case.get("conditions", []) or []:
                conds.append(_convert_condition(c))
        else:
            for c in d.get("conditions", []) or []:
                conds.append(_convert_condition(c))
        out["conditions"] = conds
        out["logical_operator"] = logical
    elif ntype == "code":
        out["code"] = str(d.get("code", "") or "")
        out["variables"] = {
            str(v.get("variable", "")): ("{{#" + ".".join(str(x) for x in (v.get("value_selector") or [])) + "#}}")
            for v in (d.get("variables") or []) if isinstance(v, dict)
        }
        out["timeout"] = d.get("timeout", 15)
    elif ntype == "template-transform":
        out["template"] = str(d.get("template", "") or "")
    elif ntype in ("end", "answer"):
        outs = []
        for o in d.get("outputs", []) or []:
            if isinstance(o, dict) and o.get("variable"):
                path = ".".join(str(x) for x in (o.get("value_selector") or []))
                outs.append({"name": o.get("variable"), "value": "{{#" + path + "#}}" if path else ""})
        out["outputs"] = outs
    return out


def _convert_condition(c: dict) -> dict:
    vs = c.get("value_selector") or c.get("variable") or []
    var = ".".join(str(x) for x in vs) if isinstance(vs, list) else str(vs)
    return {
        "variable": var,
        "operator": str(c.get("comparison_operator") or c.get("operator") or "contains"),
        "value": c.get("value", ""),
    }


def _kv_pairs(raw: Any) -> dict:
    """Dify headers 可能是 [{key,value}] 或字符串。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {str(p.get("key", "")): str(p.get("value", "")) for p in raw if isinstance(p, dict) and p.get("key")}
    return {}
