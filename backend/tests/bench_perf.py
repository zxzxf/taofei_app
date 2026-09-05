"""7.7 性能基准测试 —— 关键链路耗时量化 + 防回归宽松阈值。

覆盖（对应各阶段验收指标的本地可测部分）：
  1. 会话列表读取（Session 化架构）：200 会话 list_sessions < 200ms
  2. 消息批量写入（增量持久化）：100 条追加 < 600ms
  3. 会话加载（含消息）：50 条消息 load_session < 100ms
  4. FTS5 全文检索（Hermes D4 验收 <1s）：200 会话索引 + 查询 < 1200ms
  5. 工具 schema 构建（每轮请求固定开销）：get_all_tools+schema < 60ms
  6. n-gram embedding fallback（离线记忆可用性）：100 词向量化 < 200ms
  7. 前缀缓存友好性（system 组装）：build 固定前缀 100 次去重比 ≈ 恒定（非耗时项，仅记录）

运行：cd backend && python -m tests.bench_perf [--json]
输出：每项耗时与通过/失败；--json 时输出机器可读摘要。
说明：阈值取宽松 2-3 倍余量（CI/虚拟机波动容忍），主要防数量级回归；
      真机首次冷启动（含导入）不计入单项。
"""
import argparse
import json
import os
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 独立临时 DB，避免污染开发数据
_tmp_db = tempfile.mktemp(suffix=".db")
os.environ["TAOFEI_DB_PATH"] = _tmp_db

import db  # noqa: E402

db.init_db()


def _elapsed(fn):
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000  # ms


def _make_fixture(session_count=200, msgs_per=10):
    """建 N 会话 × M 消息的测试库（内容带可检索词）。"""
    from session.manager import get_session_manager

    mgr = get_session_manager()
    ws_id = f"bench-ws-{uuid.uuid4().hex[:6]}"
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO workspaces (id, name, path, current) VALUES (?,?,?,0)",
            (ws_id, "基准测试", f"/tmp/bench_{ws_id}"),
        )
        conn.commit()
    session_ids = []
    for i in range(session_count):
        s = mgr.create(title=f"基准会话 {i}", workspace_id=ws_id)
        session_ids.append(s.id)
        # 直接写消息（绕 LLM）
        msgs = [
            {
                "role": "user" if j % 2 == 0 else "assistant",
                "content": f"第 {i} 会话第 {j} 条消息：关于苹果香蕉橙子的讨论 quadralithic-{i}-{j}",
            }
            for j in range(msgs_per)
        ]
        db.append_session_messages(s.id, msgs)
    # 重建 FTS（若 append 已自动维护则此处幂等无害）
    try:
        db.rebuild_session_fts()
    except Exception:
        pass
    return ws_id, session_ids


BENCHES = []


def bench(name, limit_ms, fn):
    """执行并记录；返回 (name, ms, limit_ms, passed)。"""
    ms = _elapsed(fn)
    BENCHES.append({"name": name, "ms": round(ms, 2), "limit_ms": limit_ms, "passed": ms <= limit_ms})
    return ms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    args = parser.parse_args()

    print("== 7.7 性能基准 ==")
    print(f"构建基准库（200 会话 × 10 条消息）…")
    t0 = time.perf_counter()
    ws_id, session_ids = _make_fixture()
    print(f"  构建完成 {round((time.perf_counter() - t0) * 1000)}ms\n")

    # 1. 会话列表
    def _list():
        db.list_sessions(limit=200, workspace_id=ws_id)

    bench("1. list_sessions ×200", 200, _list)

    # 2. 消息批量追加
    batch = [{"role": "user", "content": f"性能压测消息 {i} quadralithic-{uuid.uuid4().hex[:6]}"} for i in range(100)]

    def _append():
        db.append_session_messages(session_ids[0], batch)

    bench("2. 追加 100 条消息", 600, _append)

    # 3. 会话加载
    def _load():
        db.load_session(session_ids[0])

    bench("3. load_session (110 条)", 100, _load)

    # 4. FTS5 检索
    def _search():
        hits = db.search_sessions("quadralithic", limit=10)
        assert len(hits) >= 1, "FTS 检索应有命中"

    bench("4. FTS5 全文检索 (2000 条索引)", 1200, _search)

    # 5. 工具 schema 构建（预热一次排除模块导入冷启动，测每轮请求稳态开销）
    def _schema():
        from agent_tools import get_all_tools, tools_to_openai_functions

        tools_to_openai_functions(get_all_tools())

    _schema()  # 预热：首次会触发 registry 扫描导入全部工具模块
    bench("5. 工具 schema 构建(热)", 60, _schema)

    # 6. n-gram embedding（单句离线向量化路径）
    def _embed():
        from embedding import get_embedding

        for i in range(20):
            get_embedding(f"性能基准测试句子 {i} quadralithic-{uuid.uuid4().hex[:6]}")

    bench("6. embedding ×20 句(离线)", 300, _embed)

    # 7. 记忆摘要 prompts 组装（每轮任务结束固定开销）
    def _prompt_build():
        from prompts import build_memory_summary_messages

        build_memory_summary_messages("用户请求示例", "最终回答示例")

    bench("7. 记忆摘要 prompt 组装", 20, _prompt_build)

    # 6 与 7 之间打印报告
    print("\n== 结果 ==")
    header = f"{'基准项':<32}{'耗时(ms)':>10}{'阈值(ms)':>10}  状态"
    print(header)
    print("-" * len(header.encode("gbk", "replace").decode("gbk", "replace")))
    failed = 0
    for b in BENCHES:
        mark = "✅ PASS" if b["passed"] else "❌ FAIL"
        if not b["passed"]:
            failed += 1
        print(f"{b['name']:<32}{b['ms']:>10.1f}{b['limit_ms']:>10}  {mark}")
    print("-" * len(header))
    total_ok = len(BENCHES) - failed
    print(f"通过 {total_ok}/{len(BENCHES)}")
    if args.json:
        print("\nJSON:")
        print(json.dumps({"benches": BENCHES, "passed": total_ok, "total": len(BENCHES)}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
