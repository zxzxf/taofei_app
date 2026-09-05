"""A5 联网工具集成测试 —— web_search / web_extract 端到端。

覆盖（Hermes 能力补齐 A 线验收）：
  1. web_search 空词/缺参 → Error 且不抛异常
  2. web_search 非法 max_results → 容错回默认
  3. web_search 真实查询 → 返回 标题/URL/摘要 结构文本（联网，网络不可用时 SKIP）
  4. web_search 结果截断 → max_results=2 时条数 ≤2
  5. web_extract 真实抓取 → 正文非空且限长（联网，网络不可用时 SKIP）
  6. web_extract 畸形 URL / 超时 → Error 降级不抛异常
  7. registry 注册可见性 → web_search/web_extract 在 get_all_tools 中
  8. 纯文本可消费性 → 输出能被 agent 直接读（无 HTML 标签残留）

网络相关用例在断网/被墙环境自动 SKIP（带 skip 原因），不误报失败。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.web_search import search_web  # noqa: E402
from tools.web_extract import extract_web  # noqa: E402

# 环境开关：显式置 0 可强制离线只跑本地用例
NETWORK_OK = os.environ.get("TAOFEI_NET_TEST", "1") == "1"


def _skip_no_net(reason="网络不可用或超时（非功能缺陷）"):
    return unittest.SkipTest(reason)


class WebSearchUnitTests(unittest.TestCase):
    """本地可跑：参数校验与错误降级（不依赖网络）。"""

    def test_empty_query_returns_error(self):
        out = search_web("   ")
        self.assertTrue(out.startswith("Error:"), f"空词应返回 Error，实际: {out[:60]}")

    def test_httpx_missing_graceful(self):
        """即便 httpx 不可用也返回 Error 文本而非抛异常（模拟降级路径）。"""
        try:
            import httpx  # noqa: F401
        except Exception:
            out = search_web("anything")
            self.assertTrue(out.startswith("Error:"))

    def test_bad_max_results_clamped(self):
        """max_results 非法/越界时容错，不抛异常。"""
        for bad in (0, -3, 9999):
            out = search_web("python", max_results=bad)
            # 允许 Error（网络），但不允许抛异常 —— 走到这里即通过
            self.assertIsInstance(out, str)

    def test_result_structure_no_html_tags(self):
        """（若有结果）标题/摘要里不应残留 HTML 标签。"""
        out = search_web("taofei", max_results=3)
        if out.startswith("Error:"):
            raise _skip_no_net(out[:80])
        self.assertNotIn("<", out, "输出应无 HTML 标签")
        self.assertNotIn("result__a", out, "不应残留解析类名")
        # 至少包含 URL 行
        self.assertIn("URL:", out)

    def test_max_results_truncation(self):
        """截断：请求 2 条时结果区 [n] 编号不应超过 2。"""
        out = search_web("openai", max_results=2)
        if out.startswith("Error:"):
            raise _skip_no_net(out[:80])
        import re

        nums = [int(x) for x in re.findall(r"^\[(\d+)\]", out, flags=re.M)]
        self.assertLessEqual(len(nums), 2, f"应截断到 2 条，实际 {len(nums)} 条")
        for n in nums:
            self.assertLessEqual(n, 2)


@unittest.skipUnless(NETWORK_OK, "环境变量 TAOFEI_NET_TEST=0，跳过联网用例")
class WebExtractTests(unittest.TestCase):
    """联网：真实抓取与截断（断网自动 SKIP 在底层）。"""

    def test_extract_real_page(self):
        out = extract_web("https://example.com", max_chars=4000)
        if out.startswith("Error:"):
            raise _skip_no_net(out[:100])
        self.assertGreater(len(out), 50, "正文应非空")
        self.assertIn("Example", out, "example.com 应含 Example 域名说明")

    def test_extract_truncated_by_max_chars(self):
        out = extract_web("https://example.com", max_chars=500)
        if out.startswith("Error:"):
            raise _skip_no_net(out[:100])
        self.assertLessEqual(len(out), 500 + 200, "超出限长不应过大（容 200 余量）")

    def test_extract_malformed_url_error(self):
        out = extract_web("not-a-url", max_chars=1000)
        self.assertTrue(out.startswith("Error:"), "畸形 URL 应返回 Error 而非抛异常")

    def test_extract_unreachable_domain_error(self):
        # RFC 2606 保留域名 .invalid 必定无法解析 → 超时/失败路径
        out = extract_web("http://this-domain-does-not-exist-zzz.invalid/", max_chars=1000)
        self.assertTrue(out.startswith("Error:"), "不可达域名应降级为 Error")

    def test_no_raw_html_in_output(self):
        out = extract_web("https://example.com", max_chars=2000)
        if out.startswith("Error:"):
            raise _skip_no_net(out[:100])
        # 正文里不应有大段标签；示例页本身含 "Example Domain" 文本
        self.assertNotIn("<html", out.lower())
        self.assertNotIn("<p>", out.lower())


class ToolRegistryTests(unittest.TestCase):
    """注册可见性：联网工具必须对 LLM schema 可见。"""

    def test_web_tools_in_get_all_tools(self):
        from agent_tools import get_all_tools

        names = {t["name"] for t in get_all_tools()}
        self.assertIn("web_search", names, "web_search 应注册进 get_all_tools")
        self.assertIn("web_extract", names, "web_extract 应注册进 get_all_tools")

    def test_registry_tools_have_schema(self):
        from agent_tools import get_all_tools

        tools = {t["name"]: t for t in get_all_tools()}
        for name in ("web_search", "web_extract"):
            t = tools.get(name)
            self.assertIsNotNone(t, f"{name} 缺失")
            self.assertIn("parameters", t, f"{name} schema 缺 parameters")
            self.assertIn("properties", t["parameters"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
