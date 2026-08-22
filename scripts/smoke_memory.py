"""记忆功能集成冒烟测试（模块级，无需启动服务）。

用法：.venv\\Scripts\\python.exe scripts/smoke_memory.py
"""

import json
import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import db
import memory

tmp = pathlib.Path(tempfile.mkdtemp()) / "smoke.db"
db.DB_FILE = tmp
db.setup()

# 准备两个工作空间
conn = db._get_conn()
conn.execute("INSERT INTO workspaces (id, name, path, current) VALUES ('ws-a', 'A', 'C:/a', 1)")
conn.execute("INSERT INTO workspaces (id, name, path, current) VALUES ('ws-b', 'B', 'C:/b', 0)")
conn.commit()
conn.close()

print("[1/4] 保存记忆（mock LLM 摘要）")
def fake_llm(messages):
    return json.dumps({"summary": "taofei_app 使用 CrewAI + FastAPI", "facts": ["SQLite 持久化", "RAG 已实现"]}, ensure_ascii=False)

ok = memory.save_memory(fake_llm, "ws-a", "分析技术栈", "结论：CrewAI + FastAPI")
assert ok, "保存失败"
print("  ok: 已保存 1 条")

print("[2/4] 同工作空间召回")
hits = memory.recall_memory("项目用什么框架", "ws-a", top_k=5)
assert hits and "CrewAI" in hits[0]["summary"], hits
print(f"  ok: 命中 {len(hits)} 条，首条含 CrewAI")

print("[3/4] 跨工作空间隔离")
hits_b = memory.recall_memory("项目用什么框架", "ws-b", top_k=5)
assert hits_b == [], hits_b
print("  ok: ws-b 未召回 ws-a 的记忆")

print("[4/4] 上下文拼装与清理")
ctx = memory.build_memory_context("继续优化", hits)
assert "继续优化" in ctx and "CrewAI" in ctx
memory.delete_memory(hits[0]["id"])
assert memory.list_memories("ws-a") == []
print("  ok: 上下文拼装正常，删除成功")

print("\nSMOKE OK")
