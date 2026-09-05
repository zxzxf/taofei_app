"""memory_tool 快速冒烟测试。

验证：memory_save → memory_recall → memory_list → memory_forget 全链路
运行：cd backend && python -m tests.test_memory_tool
"""

import os
import sys
import tempfile

# 确保能 import backend 下的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 用临时 DB 测试
_tmp_db = tempfile.mktemp(suffix=".db")
os.environ["TAOFEI_DB_PATH"] = _tmp_db

import db  # noqa: E402
import uuid as _uuid  # noqa: E402
from tools.memory_tool import (  # noqa: E402
    memory_save,
    memory_recall,
    memory_forget,
    memory_list,
)

# 初始化 DB
db.init_db()

# 创建一个测试工作空间（用唯一路径避免冲突）
FAKE_WS = f"/tmp/test_ws_{_uuid.uuid4().hex[:8]}"
ws_id = str(_uuid.uuid4())
with db._get_conn() as conn:
    conn.execute(
        "INSERT INTO workspaces (id, name, path, current) VALUES (?, ?, ?, ?)",
        (ws_id, "测试工作空间", FAKE_WS, 0),
    )
    conn.commit()


def test_save_basic():
    """测试1: 基本保存功能"""
    print("=" * 60)
    print("测试1: memory_save 基本保存")
    print("=" * 60)

    r1 = memory_save(FAKE_WS, "用户偏好中文回答，代码要带详细注释", kind="workspace_fact")
    print(f"  保存记忆1: {r1['observation'][:60]}...")
    assert r1["error"] == "", f"保存失败: {r1}"
    assert "记忆已保存" in r1["observation"]

    r2 = memory_save(FAKE_WS, "本项目使用 Vue3 + Python FastAPI 技术栈", kind="workspace_fact")
    print(f"  保存记忆2: {r2['observation'][:60]}...")
    assert r2["error"] == ""

    r3 = memory_save(FAKE_WS, "上次部署遇到的坑：PyInstaller 需要显式 import 延迟加载模块")
    print(f"  保存记忆3: {r3['observation'][:60]}...")
    assert r3["error"] == ""

    print("  ✅ 通过\n")


def test_recall():
    """测试2: memory_recall 语义召回"""
    print("=" * 60)
    print("测试2: memory_recall 语义召回")
    print("=" * 60)

    r = memory_recall(FAKE_WS, "项目用的什么技术框架？", top_k=3)
    print(f"  召回「技术框架」结果（前 300 字）:")
    print(f"  {r['observation'][:300]}")
    assert r["error"] == ""
    # 应该能召回技术栈相关的记忆
    assert "Vue3" in r["observation"] or "FastAPI" in r["observation"] or "技术栈" in r["observation"], \
        f"召回应该命中技术栈相关记忆，实际: {r['observation'][:200]}"

    print("  ✅ 通过\n")


def test_list():
    """测试3: memory_list 列出记忆"""
    print("=" * 60)
    print("测试3: memory_list 列出记忆")
    print("=" * 60)

    r = memory_list(FAKE_WS, limit=10)
    print(f"  全部记忆（前 400 字）:\n{r['observation'][:400]}")
    assert r["error"] == ""
    assert "共 3 条" in r["observation"], f"应该有 3 条记忆: {r['observation'][:50]}"

    # 按类型过滤
    r2 = memory_list(FAKE_WS, kind="workspace_fact")
    print(f"\n  workspace_fact 类型:\n{r2['observation'][:200]}")
    assert r2["error"] == ""
    assert "2 条" in r2["observation"], f"应该有 2 条 workspace_fact: {r2['observation'][:80]}"

    # 测试 limit
    r3 = memory_list(FAKE_WS, limit=1)
    assert "共 1 条" in r3["observation"], f"limit=1 应该只返回 1 条"

    print("  ✅ 通过\n")


def test_forget_by_id():
    """测试4: memory_forget 按 ID 删除"""
    print("=" * 60)
    print("测试4: memory_forget 按 ID 删除")
    print("=" * 60)

    # 先列出来拿 ID
    r = memory_list(FAKE_WS, limit=1)
    import re
    m = re.search(r"ID: ([a-f0-9]+)…", r["observation"])
    assert m, f"没找到记忆 ID: {r['observation'][:100]}"
    mem_id_prefix = m.group(1)
    print(f"  记忆 ID 前缀: {mem_id_prefix}")

    r2 = memory_forget(FAKE_WS, memory_id=mem_id_prefix)
    print(f"  删除结果: {r2['observation']}")
    assert r2["error"] == ""
    assert "已删除 1 条" in r2["observation"]

    # 验证只剩 2 条
    r3 = memory_list(FAKE_WS)
    assert "共 2 条" in r3["observation"], f"删除后应该剩 2 条: {r3['observation'][:50]}"

    print("  ✅ 通过\n")


def test_forget_by_keyword():
    """测试5: memory_forget 按关键词删除"""
    print("=" * 60)
    print("测试5: memory_forget 按关键词删除")
    print("=" * 60)

    r = memory_forget(FAKE_WS, keyword="PyInstaller")
    print(f"  按关键词「PyInstaller」删除: {r['observation']}")
    assert r["error"] == ""
    # 删除了 0 或 1 条都算正常（取决于之前删 ID 删掉的是哪条）
    n_deleted = int(r["observation"].split("已删除 ")[1].split(" 条")[0])
    assert n_deleted in (0, 1), f"删除数量异常: {n_deleted}"

    # 验证剩余数量
    r2 = memory_list(FAKE_WS)
    count = int(r2["observation"].split("共 ")[1].split(" 条")[0])
    assert count >= 1, f"至少应该剩 1 条"
    print(f"  删除后剩余 {count} 条记忆")

    print("  ✅ 通过\n")


def test_edge_cases():
    """测试6: 边界情况"""
    print("=" * 60)
    print("测试6: 边界情况")
    print("=" * 60)

    # 空内容
    r = memory_save(FAKE_WS, "")
    print(f"  空内容保存: {r['error']}")
    assert r["error"] != "", "空内容应该报错"

    # 空查询
    r = memory_recall(FAKE_WS, "")
    print(f"  空查询召回: {r['error']}")
    assert r["error"] != "", "空查询应该报错"

    # 不存在的 ID
    r = memory_forget(FAKE_WS, memory_id="nonexistent")
    print(f"  不存在的 ID 删除: {r['error']}")
    assert "未找到" in r["error"], "不存在的 ID 应该报错"

    # 无工作空间
    r = memory_list("/nonexistent/path")
    print(f"  不存在的工作空间: {r['error'] or r['observation']}")
    assert "无工作空间" in r["observation"] or r["observation"] == "暂无记忆。"

    # memory_forget 不传参数
    r = memory_forget(FAKE_WS)
    print(f"  forget 不传参数: {r['error']}")
    assert "请提供" in r["error"], "两个参数都为空应该报错"

    # kind 参数默认值
    r = memory_save(FAKE_WS, "测试默认 kind 的记忆")
    assert r["error"] == ""
    # 列出来确认是 episodic 类型
    r2 = memory_list(FAKE_WS, kind="episodic")
    assert "1 条" in r2["observation"] or "2 条" in r2["observation"], \
        f"默认 kind 应该是 episodic: {r2['observation'][:100]}"

    print("  ✅ 通过\n")


def test_registry_integration():
    """测试7: 工具注册中心集成"""
    print("=" * 60)
    print("测试7: 工具注册中心集成")
    print("=" * 60)

    from tools.registry import registry

    tools = registry.get_tools("all")
    names = [t["name"] for t in tools]
    print(f"  已注册的工具: {names}")

    assert "memory_save" in names, "memory_save 应在 registry 中"
    assert "memory_recall" in names, "memory_recall 应在 registry 中"
    assert "memory_forget" in names, "memory_forget 应在 registry 中"
    assert "memory_list" in names, "memory_list 应在 registry 中"

    # 验证 memory tag 工具集
    mem_tools = registry.get_tools("memory")
    mem_names = [t["name"] for t in mem_tools]
    assert len(mem_names) == 4, f"memory 工具集应该有 4 个工具: {mem_names}"
    print(f"  memory 工具集: {mem_names}")

    # 测试 dispatch 调用
    result = registry.dispatch(
        "memory_save",
        FAKE_WS,
        {"content": "通过 registry 保存的测试记忆", "kind": "episodic"},
    )
    print(f"  registry.dispatch(memory_save): {result['observation'][:80]}")
    assert result["error"] == "", f"dispatch 失败: {result['error']}"

    result2 = registry.dispatch("memory_list", FAKE_WS, {})
    print(f"  registry.dispatch(memory_list): {result2['observation'][:100]}")
    assert result2["error"] == ""

    # 测试 dispatch 调用 recall
    result3 = registry.dispatch(
        "memory_recall",
        FAKE_WS,
        {"query": "registry", "top_k": 3},
    )
    print(f"  registry.dispatch(memory_recall): {result3['observation'][:100]}")
    assert result3["error"] == ""

    print("  ✅ 通过\n")


def test_openai_schema():
    """测试8: OpenAI function calling schema 正确性"""
    print("=" * 60)
    print("测试8: OpenAI function calling schema")
    print("=" * 60)

    from tools.registry import registry

    functions = registry.get_openai_functions("memory")
    print(f"  共 {len(functions)} 个 function schema")

    for f in functions:
        assert f["type"] == "function"
        fn = f["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params
        print(f"    - {fn['name']}: {len(params['properties'])} 个参数, "
              f"required={params['required']}")

    # 验证 memory_save 必须有 content 参数
    save_fn = [f for f in functions if f["function"]["name"] == "memory_save"][0]
    assert "content" in save_fn["function"]["parameters"]["required"], \
        "memory_save 的 required 应该包含 content"

    print("  ✅ 通过\n")


if __name__ == "__main__":
    print(f"测试 DB: {_tmp_db}")
    print()

    tests = [
        test_save_basic,
        test_recall,
        test_list,
        test_forget_by_id,
        test_forget_by_keyword,
        test_edge_cases,
        test_registry_integration,
        test_openai_schema,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            print()

    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    # 清理
    try:
        os.unlink(_tmp_db)
    except Exception:
        pass

    sys.exit(0 if failed == 0 else 1)
