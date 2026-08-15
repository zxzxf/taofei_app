"""工作流图引擎：DAG 解析、拓扑调度、条件分支裁剪、节点事件记录。

借鉴 Dify workflow 引擎架构（graph + variable pool + node executors + 事件流），
针对本平台自研实现：无 Flask/Celery/Redis 依赖。
同一批次就绪的节点用线程池并行执行（max_workers 可配）。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .nodes import get_executor
from .variable_pool import VariablePool


class WorkflowError(Exception):
    """工作流执行错误（节点失败 / 图结构非法等）。"""


class WorkflowEngine:
    def __init__(
        self,
        graph: dict,
        *,
        llm_call: Callable[[list[dict]], str],
        log: Callable[[str, str], None] | None = None,
        python_bin: str | None = None,
        progress: Callable[[dict], None] | None = None,
        extra_ctx: dict | None = None,
        max_workers: int = 4,
    ) -> None:
        self.nodes: dict[str, dict] = {}
        for n in graph.get("nodes", []):
            self.nodes[str(n.get("id"))] = n
        self.edges: list[dict] = graph.get("edges", [])
        self.llm_call = llm_call
        self.log = log or (lambda level, msg: None)
        self.ctx: dict = {"llm_call": llm_call, "log": self._node_log, "python_bin": python_bin}
        if extra_ctx:
            self.ctx.update(extra_ctx)
        self.node_runs: list[dict] = []
        self._progress = progress           # 节点开始/结束时回调（用于实时进度）
        self._selection: dict[str, str] = {}  # ifelse 节点 id -> 选中分支 "true"/"false"
        self._lock = threading.RLock()      # 并行执行时保护共享状态
        self.max_workers = max(1, int(max_workers))

    # ---------- 内部 ----------
    def _node_log(self, level: str, message: str) -> None:
        self.log(level, message)

    def _incoming(self, node_id: str) -> list[dict]:
        return [e for e in self.edges if str(e.get("target")) == node_id]

    def _edge_active(self, edge: dict) -> bool:
        """连线是否放行：源节点已执行，且（若源是条件分支）分支被选中。"""
        src = str(edge.get("source"))
        handle = edge.get("sourceHandle")
        if src not in self._executed:
            return False
        if src in self._selection:
            selected = self._selection[src]
            if handle in ("true", "false") and handle != selected:
                return False
        return True

    # ---------- 执行 ----------
    def run(self, inputs: dict[str, Any] | None = None) -> dict:
        inputs = inputs or {}
        self._executed: set[str] = set()
        self.node_runs = []
        self._selection = {}

        # 校验图
        for n in self.nodes.values():
            if get_executor(str(n.get("type", ""))) is None:
                raise WorkflowError(f"不支持的节点类型：{n.get('type')}（{n.get('data', {}).get('title', n.get('id'))}）")

        pool = VariablePool(inputs)
        # start 节点输入预置：sys.query 与 start 变量同源
        self.log("INFO", f"工作流启动，输入：{ {k: (v[:50] + '…' if isinstance(v, str) and len(v) > 50 else v) for k, v in inputs.items()} }")

        while True:
            # 就绪判定：无入连线（根节点）立即就绪；否则任一入连线放行即可（支持分支裁剪后的汇合）
            def _ready(nid: str) -> bool:
                es = self._incoming(nid)
                if not es:
                    return True
                return any(self._edge_active(e) for e in es)

            ready = [n for nid, n in self.nodes.items() if nid not in self._executed and _ready(nid)]
            if not ready:
                break
            if len(ready) == 1:
                self._execute_node(ready[0], pool)
            else:
                self._run_batch(ready, pool)

        executed_ids = set(self._executed)
        skipped = [
            {"id": nid, "type": n.get("type"), "title": _title(n)}
            for nid, n in self.nodes.items() if nid not in executed_ids
        ]
        if skipped:
            self.log("INFO", f"跳过未激活分支节点：{'、'.join(s['title'] or s['id'] for s in skipped)}")

        outputs: dict[str, Any] = {}
        end_runs = [r for r in self.node_runs if r["type"] in ("end", "answer") and r["status"] == "succeeded"]
        if end_runs:
            for r in end_runs:
                outputs.update(r.get("outputs") or {})
        elif "end" not in self.nodes and "answer" not in self.nodes:
            # 无 end 节点：取最后一个成功节点的输出
            ok_runs = [r for r in self.node_runs if r["status"] == "succeeded"]
            if ok_runs:
                outputs = dict(ok_runs[-1].get("outputs") or {})
        self.log("INFO", f"工作流结束，输出字段：{list(outputs.keys())}")
        return {"outputs": outputs, "node_runs": self.node_runs, "skipped": skipped}

    # ---------- 并行批次 ----------
    def _run_batch(self, nodes: list[dict], pool: VariablePool) -> None:
        """同批次就绪节点并行执行：全部提交、等全部结束，再统一检查失败。

        失败语义：批次内任一节点失败，等其余节点跑完（避免半途丢失进度记录），
        然后抛出第一个错误终止工作流。
        """
        titles = "、".join(_title(n) for n in nodes)
        self.log("INFO", f"∥ 并行执行 {len(nodes)} 个节点：{titles}")
        workers = min(self.max_workers, len(nodes))
        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wf-node") as ex:
            futures = [ex.submit(self._execute_node, n, pool) for n in nodes]
            for fut in futures:
                exc = fut.exception()
                if exc is not None:
                    errors.append(exc)
        if errors:
            raise errors[0]

    # ---------- 单节点 ----------
    def _execute_node(self, node: dict, pool: VariablePool) -> None:
        node_id = str(node.get("id"))
        node_type = str(node.get("type"))
        title = _title(node)
        started = time.time()
        self.log("INFO", f"▶ 节点开始 [{title}]（{node_type}）")
        record = {"id": node_id, "type": node_type, "title": title, "status": "running", "elapsed_ms": 0, "outputs": None}
        if self._progress:
            self._progress(dict(record))
        try:
            executor = get_executor(node_type)
            assert executor is not None
            outs = executor(node, pool, self.ctx)
            with self._lock:
                pool.set(node_id, outs)
                record.update(status="succeeded", outputs=_clip(outs), elapsed_ms=int((time.time() - started) * 1000))
                self._executed.add(node_id)
                if node_type in ("ifelse", "if-else"):
                    self._selection[node_id] = str((outs or {}).get("result", "false"))
            self.log("INFO", f"✔ 节点完成 [{title}]，耗时 {record['elapsed_ms']}ms")
        except Exception as exc:  # noqa: BLE001
            record.update(status="failed", elapsed_ms=int((time.time() - started) * 1000), error=str(exc))
            with self._lock:
                self.node_runs.append(record)
            if self._progress:
                self._progress(dict(record))
            self.log("ERROR", f"✘ 节点失败 [{title}]：{exc}")
            raise WorkflowError(f"节点「{title}」执行失败：{exc}") from exc
        with self._lock:
            self.node_runs.append(record)
        if self._progress:
            self._progress(dict(record))


def _title(node: dict) -> str:
    return str(node.get("data", {}).get("title") or node.get("id"))


def _clip(obj: Any, limit: int = 2000) -> Any:
    import json

    try:
        s = json.dumps(obj, ensure_ascii=False)
        if len(s) > limit:
            return s[:limit] + "…(截断)"
        return obj
    except Exception:
        return str(obj)[:limit]
