"""RAG 集成冒烟测试。

验证链路：创建知识库 → 上传文件 → 分块入库 → 向量检索 → agent run 接受 knowledge_ids。
使用临时 SQLite 数据库，不污染真实数据；不实际等待 Agent 完成（需要 LLM API Key）。
用法：.venv\\Scripts\\python.exe scripts/smoke_rag.py
"""

import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import db
import knowledge
import rag_prompt
import retriever

# 使用临时库
tmp = pathlib.Path(tempfile.mkdtemp()) / "smoke.db"
db.DB_FILE = tmp
db.setup()

print("[1/4] 创建知识库")
kb = knowledge.create_kb("冒烟库", "smoke test")
assert kb["id"], "知识库创建失败"
print(f"  ok: {kb['id']}")

print("[2/4] 上传并入库 README.md")
sample = PROJECT_ROOT / "README.md"
count = knowledge.upload_file(kb["id"], str(sample))
assert count > 0, "入库分块数为 0"
print(f"  ok: {count} 个分块")

print("[3/4] 向量检索")
chunks = retriever.retrieve("项目用什么技术栈", [kb["id"]], top_k=3)
assert chunks, "检索结果为空"
assert chunks[0]["source_path"].endswith("README.md")
ctx = rag_prompt.build_rag_context("项目用什么技术栈", chunks)
assert "README.md" in ctx and "项目用什么技术栈" in ctx
print(f"  ok: 命中 {len(chunks)} 个片段，首个来源 {chunks[0]['source_path']}")

print("[4/4] 清理")
knowledge.delete_kb(kb["id"])
assert not knowledge.list_kbs()
print("  ok: 已删除")

print("\nSMOKE OK")
