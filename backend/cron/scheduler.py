"""CronScheduler —— 轻量定时任务调度器（7.6 Cron，无第三方依赖）。

- 任务配置持久化到 JSON 文件（默认 backend/data/cron_jobs.json）
- 守护线程每 20s tick 一次，检查到期任务并触发执行
- 执行器由宿主（main.py）注入：executor(job) -> dict（同步调用，内部自行起线程不阻塞）
- 时间语义：
    * every:N  → 每 N 分钟（N>=1）
    * cron 5 段  → "分 时 日 月 周"，支持 * / 数字 / */步长 / 逗号列表
- 错过补跑：到期才跑一次；执行完毕从当前时刻重算下次，不做积压补跑（防雪崩）
- 线程安全：jobs 字典 + 文件写均加锁
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

DEFAULT_JOBS_FILE = os.environ.get(
    "TAOFEI_CRON_JOBS",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cron_jobs.json"
    ),
)

# cron 字段顺序（标准 5 段）：分 时 日 月 周
_FIELD_RANGES = (
    (0, 59),    # minute
    (0, 23),    # hour
    (1, 31),    # day of month
    (1, 12),    # month
    (0, 6),     # day of week (0=Sunday)
)

_TICK_SECONDS = 20


def parse_cron_expr(expr: str) -> Optional[list[set[int]]]:
    """解析 5 段 cron 表达式；不合法返回 None。返回每字段允许值的集合列表。"""
    expr = (expr or "").strip()
    if not expr or ";" in expr:
        return None
    parts = expr.split()
    if len(parts) != 5:
        return None
    fields: list[set[int]] = []
    for raw, (lo, hi) in zip(parts, _FIELD_RANGES):
        allowed: set[int] = set()
        for token in raw.split(","):
            token = token.strip()
            if not token:
                return None
            step = 1
            base = token
            if "/" in token:
                base, _, step_s = token.partition("/")
                try:
                    step = int(step_s)
                except ValueError:
                    return None
                if step <= 0:
                    return None
            if base == "*":
                rng = range(lo, hi + 1)
            elif "-" in base:
                try:
                    a, b = base.split("-", 1)
                    a, b = int(a), int(b)
                except ValueError:
                    return None
                if not (lo <= a <= b <= hi):
                    return None
                rng = range(a, b + 1)
            else:
                try:
                    single = int(base)
                except ValueError:
                    return None
                if not (lo <= single <= hi):
                    return None
                rng = range(single, single + 1)
            for v in rng:
                if v % step == 0:
                    allowed.add(v)
        if not allowed:
            return None
        fields.append(allowed)
    return fields


def cron_matches(dt: datetime, fields: list[set[int]]) -> bool:
    """判断时间是否匹配已解析的 cron 字段（本地时区）。

    周字段用标准 cron 语义：0=Sunday … 6=Saturday；Python weekday() 为
    0=Monday … 6=Sunday，故做 (weekday()+1) % 7 转换。
    """
    if len(fields) != 5:
        return False
    cron_dow = (dt.weekday() + 1) % 7
    return (
        dt.minute in fields[0]
        and dt.hour in fields[1]
        and dt.day in fields[2]
        and dt.month in fields[3]
        and cron_dow in fields[4]
    )


def next_cron_run(dt: datetime, fields: list[set[int]], max_scan_minutes: int = 60 * 24 * 30) -> Optional[datetime]:
    """从 dt 之后找下一个匹配时刻（分钟粒度，向后扫）。扫不到返回 None。"""
    probe = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(max_scan_minutes):
        if cron_matches(probe, fields):
            return probe
        probe += timedelta(minutes=1)
    return None


class CronScheduler:
    def __init__(self, jobs_file: str = DEFAULT_JOBS_FILE):
        self.jobs_file = jobs_file
        self._jobs: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._executor: Optional[Callable[[dict], dict]] = None

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------
    def start(self, executor: Callable[[dict], dict]) -> None:
        """启动调度线程。executor(job) 执行任务，返回结果 dict（由宿主负责非阻塞）。"""
        self._executor = executor
        self._stop.clear()
        self._load()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="cron-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - 调度循环绝不因单个异常退出
                print(f"[cron] tick 异常：{exc}", flush=True)
            self._stop.wait(_TICK_SECONDS)

    # ------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------
    def _load(self) -> None:
        try:
            if os.path.exists(self.jobs_file):
                with open(self.jobs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._jobs = {j["id"]: j for j in data if isinstance(j, dict) and j.get("id")}
        except Exception as exc:
            print(f"[cron] 加载任务文件失败：{exc}", flush=True)
            self._jobs = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.jobs_file), exist_ok=True)
            with open(self.jobs_file, "w", encoding="utf-8") as f:
                json.dump(list(self._jobs.values()), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[cron] 保存任务文件失败：{exc}", flush=True)

    # ------------------------------------------------------------
    # jobs CRUD（线程安全）
    # ------------------------------------------------------------
    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in self._jobs.values()]

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def _default_next_run(self, job: dict) -> Optional[str]:
        """按 schedule 类型计算首次/下次运行时刻（ISO 字符串或 None）。"""
        sched = (job.get("schedule") or "").strip()
        now = datetime.now()
        if sched.startswith("every:"):
            try:
                minutes = max(1, int(sched.split(":", 1)[1]))
            except ValueError:
                minutes = 1
            return (now + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        fields = parse_cron_expr(sched)
        if fields:
            nxt = next_cron_run(now, fields)
            return nxt.isoformat(timespec="seconds") if nxt else None
        return None

    def upsert_job(self, job: dict) -> dict:
        """新增或更新任务。字段：id(name 用 uuid 生成)/name/schedule/prompt/
        workspace_id/preset_id/enabled。返回规范化后的 job。"""
        job_id = (job.get("id") or "").strip()
        if not job_id:
            import uuid

            job_id = uuid.uuid4().hex[:12]
        with self._lock:
            existing = self._jobs.get(job_id, {})
            merged = {
                "id": job_id,
                "name": (job.get("name") or existing.get("name") or "定时任务").strip(),
                "schedule": (job.get("schedule") or existing.get("schedule") or "every:60").strip(),
                "prompt": (job.get("prompt") or existing.get("prompt") or "").strip(),
                "workspace_id": job.get("workspace_id") or existing.get("workspace_id") or "",
                "preset_id": job.get("preset_id") or existing.get("preset_id") or "",
                "enabled": bool(job.get("enabled", existing.get("enabled", True))),
                "created_at": existing.get("created_at") or datetime.now().isoformat(timespec="seconds"),
                "last_run_at": existing.get("last_run_at"),
                "last_status": existing.get("last_status"),
                "last_result": existing.get("last_result"),
                "last_task_id": existing.get("last_task_id"),
                "next_run_at": existing.get("next_run_at") or self._default_next_run(
                    {**existing, **job}
                ),
            }
            # schedule 变了 → 重算 next_run
            if job.get("schedule") and job["schedule"].strip() != existing.get("schedule"):
                merged["next_run_at"] = self._default_next_run(merged)
            if not merged["prompt"]:
                raise ValueError("任务内容 prompt 不能为空")
            self._jobs[job_id] = merged
            self._save()
            return dict(merged)

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            del self._jobs[job_id]
            self._save()
            return True

    def run_now(self, job_id: str) -> Optional[dict]:
        """手动立即触发一次。返回 job 快照；不存在返回 None。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            snapshot = dict(job)
        self._execute(snapshot)
        return snapshot

    # ------------------------------------------------------------
    # 调度核心
    # ------------------------------------------------------------
    def _tick(self) -> None:
        now = datetime.now()
        with self._lock:
            due = [
                dict(j)
                for j in self._jobs.values()
                if j.get("enabled")
                and j.get("prompt")
                and j.get("next_run_at")
                and _iso_to_dt(j["next_run_at"]) <= now
            ]
        for job in due:
            self._execute(job)

    def _execute(self, job: dict) -> None:
        """同步占位并推进 next_run，然后丢给执行器（宿主自管线程）。"""
        job_id = job["id"]
        with self._lock:
            cur = self._jobs.get(job_id)
            if not cur:
                return
            cur["last_run_at"] = datetime.now().isoformat(timespec="seconds")
            cur["last_status"] = "running"
            cur["last_result"] = ""
            # 推进下次运行（从当前时刻起算，防积压）
            sched = (cur.get("schedule") or "").strip()
            if sched.startswith("every:"):
                try:
                    minutes = max(1, int(sched.split(":", 1)[1]))
                except ValueError:
                    minutes = 1
                cur["next_run_at"] = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            else:
                fields = parse_cron_expr(sched)
                nxt = next_cron_run(datetime.now(), fields) if fields else None
                cur["next_run_at"] = nxt.isoformat(timespec="seconds") if nxt else None
            self._save()
            snapshot = dict(cur)

        if not self._executor:
            print("[cron] 执行器未注入，跳过执行", flush=True)
            return

        def _run_and_record():
            result: dict = {}
            try:
                result = self._executor(snapshot) or {}
            except Exception as exc:  # noqa: BLE001 - 执行失败只记录
                result = {"error": f"{type(exc).__name__}: {exc}"}
            with self._lock:
                cur = self._jobs.get(job_id)
                if cur:
                    status = "ok" if not result.get("error") else "failed"
                    cur["last_status"] = status
                    cur["last_result"] = (result.get("error") or result.get("summary") or "")[:200]
                    cur["last_task_id"] = result.get("task_id")
                    self._save()

        threading.Thread(target=_run_and_record, daemon=True, name=f"cron-run-{job_id}").start()


def _iso_to_dt(iso: str) -> datetime:
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return datetime.min


# 全局单例（main.py import 后注入 executor 并 start）
scheduler = CronScheduler()
