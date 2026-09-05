"""CronScheduler 单元测试（7.6 Cron，纯本地不联网/不起 LLM）。

覆盖：
  1. cron 表达式解析：* / 数字 / */步长 / 逗号 / 非法值
  2. cron_matches：具体时刻命中判定
  3. next_cron_run：向后扫描最近匹配（含跨天）
  4. every:N 快捷模式的 next 推进
  5. 持久化：upsert → 文件 → 重新加载
  6. _tick：到期任务触发执行器、last_status 记录、next_run 推进
  7. 错过不积压：禁用任务不触发

运行：cd backend && python -m tests.test_cron_scheduler
"""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cron.scheduler import (  # noqa: E402
    CronScheduler,
    cron_matches,
    next_cron_run,
    parse_cron_expr,
)

_TMP = tempfile.mktemp(suffix="_cron_jobs.json")


def _iso_dt(iso):
    return datetime.fromisoformat(iso)


class ParseTests(unittest.TestCase):
    def test_full_star(self):
        fields = parse_cron_expr("* * * * *")
        self.assertEqual(len(fields), 5)
        self.assertIn(0, fields[0])
        self.assertIn(59, fields[0])
        self.assertIn(6, fields[4])  # 周 0-6

    def test_step(self):
        fields = parse_cron_expr("*/15 * * * *")
        self.assertIn(0, fields[0])
        self.assertIn(15, fields[0])
        self.assertNotIn(14, fields[0])

    def test_list_and_range(self):
        fields = parse_cron_expr("0,30 9-11 * * 1-5")
        self.assertEqual(fields[0], {0, 30})
        self.assertEqual(fields[1], {9, 10, 11})
        self.assertEqual(fields[4], {1, 2, 3, 4, 5})

    def test_invalid(self):
        for bad in ("", "1 2", "a b c d e", "61 * * * *", "0 24 * * *", "0 * * * 8", "*/0 * * * *"):
            self.assertIsNone(parse_cron_expr(bad), f"应拒绝非法表达式: {bad!r}")


class MatchTests(unittest.TestCase):
    def test_daily_9_30(self):
        fields = parse_cron_expr("30 9 * * *")
        self.assertTrue(cron_matches(datetime(2026, 9, 5, 9, 30), fields))
        self.assertFalse(cron_matches(datetime(2026, 9, 5, 9, 31), fields))
        self.assertFalse(cron_matches(datetime(2026, 9, 5, 10, 30), fields))

    def test_weekday_restrict(self):
        # 标准 cron 周语义：0=周日 … 6=周六
        fields = parse_cron_expr("0 8 * * 1-5")  # 周一至周五
        # 2026-09-05 是周六（cron 6）→ 不命中
        self.assertFalse(cron_matches(datetime(2026, 9, 5, 8, 0), fields))
        # 2026-09-07 是周一（cron 1）→ 命中
        self.assertTrue(cron_matches(datetime(2026, 9, 7, 8, 0), fields))
        # 周日边界：2026-09-06（cron 0）
        fields_sun = parse_cron_expr("0 8 * * 0")  # 仅周日
        self.assertTrue(cron_matches(datetime(2026, 9, 6, 8, 0), fields_sun))
        self.assertFalse(cron_matches(datetime(2026, 9, 7, 8, 0), fields_sun))


class NextRunTests(unittest.TestCase):
    def test_next_minute(self):
        fields = parse_cron_expr("* * * * *")
        nxt = next_cron_run(datetime(2026, 9, 5, 10, 0, 30), fields)
        self.assertEqual(nxt, datetime(2026, 9, 5, 10, 1))

    def test_next_daily_cross_midnight(self):
        fields = parse_cron_expr("0 3 * * *")  # 每天 03:00
        nxt = next_cron_run(datetime(2026, 9, 5, 10, 0), fields)
        self.assertEqual(nxt, datetime(2026, 9, 6, 3, 0))

    def test_step_hourly(self):
        fields = parse_cron_expr("0 */2 * * *")
        nxt = next_cron_run(datetime(2026, 9, 5, 9, 0), fields)
        self.assertEqual(nxt, datetime(2026, 9, 5, 10, 0))


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.s = CronScheduler(_TMP)
        self.calls = []

        def fake_executor(job):
            self.calls.append(job.get("id"))
            return {"task_id": "task-" + job["id"], "summary": "done"}

        self.s._executor = fake_executor

    def test_upsert_persist_reload(self):
        job = self.s.upsert_job({
            "name": "测试任务", "schedule": "every:5",
            "prompt": "定时检查服务状态", "enabled": True,
        })
        self.assertTrue(job["id"])
        self.assertIsNotNone(job["next_run_at"])
        # 重新加载文件
        s2 = CronScheduler(_TMP)
        s2._load()
        jobs = s2.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["name"], "测试任务")

    def test_every_next_run_advance(self):
        job = self.s.upsert_job({
            "name": "每2分钟", "schedule": "every:2", "prompt": "hi", "enabled": True,
        })
        first = _iso_dt(job["next_run_at"])
        # 把 next 改为过去，触发执行
        past = (datetime.now().replace(second=0, microsecond=0) - __import__("datetime").timedelta(seconds=5)).isoformat(timespec="seconds")
        with self.s._lock:
            self.s._jobs[job["id"]]["next_run_at"] = past
        self.s._tick()
        time.sleep(0.2)  # 执行线程记录结果
        updated = self.s.get_job(job["id"])
        self.assertIn(updated["id"], self.calls)
        self.assertEqual(updated["last_status"], "ok")
        self.assertIsNotNone(updated["last_task_id"])
        new_next = _iso_dt(updated["next_run_at"])
        self.assertGreater(new_next, first - __import__("datetime").timedelta(minutes=3))

    def test_disabled_job_not_fired(self):
        job = self.s.upsert_job({
            "name": "禁用任务", "schedule": "every:1", "prompt": "x",
            "enabled": False,
        })
        with self.s._lock:
            self.s._jobs[job["id"]]["next_run_at"] = (datetime.now().replace(second=0, microsecond=0) - __import__("datetime").timedelta(seconds=5)).isoformat(timespec="seconds")
        self.s._tick()
        time.sleep(0.1)
        self.assertNotIn(job["id"], self.calls)

    def test_delete(self):
        job = self.s.upsert_job({"name": "删除我", "schedule": "every:60", "prompt": "x"})
        self.assertTrue(self.s.delete_job(job["id"]))
        self.assertFalse(self.s.delete_job(job["id"]))

    def test_prompt_required(self):
        with self.assertRaises(ValueError):
            self.s.upsert_job({"name": "空内容", "schedule": "every:60", "prompt": "  "})


if __name__ == "__main__":
    unittest.main(verbosity=2)
