"""web_search.py —— 基于免费网页接口的搜索工具（无 API key）。

- 首选 DuckDuckGo HTML 接口（html.duckduckgo.com/html 与
  lite.duckduckgo.com/lite），解析标题/URL/摘要；
- DDG 被反爬或解析不到结果时自动兜底 Bing 搜索结果页；
- 内置 User-Agent 与 15 秒超时；
- 对外只暴露 search_web(query, max_results=5) -> str：任何情况下都不抛异常，
  出错统一返回 'Error: ...' 开头的字符串（便于 agent 以纯文本方式消费）。
"""

try:
    import httpx
except Exception as _import_err:  # pragma: no cover - 容错兜底
    httpx = None
    _IMPORT_ERROR = f"httpx 未安装或导入失败: {_import_err}"
else:
    _IMPORT_ERROR = None

import base64 as _base64
import html as _html
import re as _re
from urllib.parse import urljoin

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_ENDPOINTS = (
    "https://html.duckduckgo.com/html/",
    "https://lite.duckduckgo.com/lite/",
)

# 常见非 https 相对/畸形链接前缀，用于丢弃噪音
_SKIP_URL_PREFIXES = ("//duckduckgo.com/", "//www.duckduckgo.com/", "javascript:")


def _clean_text(s: str) -> str:
    """去掉 HTML 标签、多余空白，还原常见实体。"""
    if not s:
        return ""
    s = _re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    return _re.sub(r"\s+", " ", s).strip()


def _parse_results(html_text: str, base_url: str) -> list[dict]:
    """从 DDG HTML 结果页解析出 [{"title","url","snippet"}] 列表。

    兼容 html.duckduckgo.com/html 的 result__a / result__snippet 结构，
    也兼容 lite 版的 result-link / result-snippet 表格结构。
    采用“位置扫描”法：先定位每条结果链接锚点，再在相邻锚点之间的
    区间里找摘要，避免块级正则被嵌套结构破坏。
    """
    results: list[dict] = []

    def _pick(kind: str) -> tuple[list[tuple[int, int, str, str]], str]:
        """返回 ([(链接起点, 链接结束位置, url, title)], snippet类名)；kind 为两种页面结构之一。"""
        if kind == "html":
            link_cls, snip_cls = "result__a", "result__snippet"
        else:
            link_cls, snip_cls = "result-link", "result-snippet"
        found: list[tuple[int, int, str, str]] = []
        pat = _re.compile(
            rf'<a[^>]*class="[^"]*{link_cls}[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            flags=_re.S,
        )
        for m in pat.finditer(html_text):
            found.append((m.start(), m.end(), m.group(1), m.group(2)))
        return found, snip_cls

    for kind in ("html", "lite"):
        links, snip_cls = _pick(kind)
        for i, (_, end, href, title_html) in enumerate(links):
            href = _html.unescape(href.strip())
            # DDG 的 href 常为重定向包装（//duckduckgo.com/l/?uddg=<编码后的真实URL>）
            if "uddg=" in href:
                inner = _re.search(r"[?&]uddg=([^&]+)", href)
                if inner:
                    href = inner.group(1)
            url = urljoin(base_url, href)
            if not url.lower().startswith("https://"):
                continue
            title = _clean_text(title_html)
            # 摘要取“本链接结束 ～ 下一条链接开始”区间内的第一个 snippet
            window_end = links[i + 1][0] if i + 1 < len(links) else len(html_text)
            window = html_text[end:window_end]
            m_snip = _re.search(
                rf'<a[^>]*class="[^"]*{snip_cls}[^"]*"[^>]*>(.*?)</a>',
                window,
                flags=_re.S,
            )
            if not m_snip:  # lite 版摘要有时是 <td> 文本而非链接
                m_snip = _re.search(
                    rf'class="[^"]*{snip_cls}[^"]*"[^>]*>(.*?)</(?:a|td)>',
                    window,
                    flags=_re.S,
                )
            snippet = _clean_text(m_snip.group(1)) if m_snip else ""
            if url and title:
                results.append({"title": title, "url": url, "snippet": snippet})
        if results:
            return results
    return results


def _dedupe(results: list[dict]) -> list[dict]:
    """按 URL 去重（保留首个），并剔除明显是导航/无关链接的条目。"""
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        u = r["url"].lower()
        if u in seen or any(u.startswith(p) for p in _SKIP_URL_PREFIXES):
            continue
        seen.add(u)
        out.append(r)
    return out


def _decode_bing_url(href: str) -> str:
    """Bing 的 ck/a 重定向链接中，真实 URL 以 base64 存在 u= 参数里。

    形如 https://www.bing.com/ck/a?...&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS8 ，
    'a1' 之后是 urlsafe base64 编码的目标地址。
    """
    if "bing.com/ck/" not in href:
        return href
    m = _re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", href)
    if not m:
        return href
    try:
        padded = m.group(1) + "=" * (-len(m.group(1)) % 4)
        return _base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "replace")
    except Exception:
        return href


def _search_bing(query: str) -> list[dict]:
    """Bing 兜底搜索（DDG 被反爬/不可用时启用），解析 <li class="b_algo"> 结果块。"""
    url = "https://www.bing.com/search"
    resp = httpx.get(
        url,
        params={"q": query},
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"},
        timeout=15.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    html_text = resp.text
    results: list[dict] = []

    # 定位每个 b_algo 结果块（下一个 b_algo 出现处即本块结束）
    starts = [m.start() for m in _re.finditer(r'<li class="b_algo"', html_text)]
    for idx, s in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(html_text)
        block = html_text[s:end]
        # 标题链接：h2 内的首个 <a>
        m_link = _re.search(r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                            block, flags=_re.S)
        if not m_link:
            continue
        href = _html.unescape(m_link.group(1))
        url_real = _decode_bing_url(href)
        if not url_real.lower().startswith(("https://", "http://")):
            continue
        title = _clean_text(m_link.group(2))
        # 摘要：b_caption 内的段落文本
        m_cap = _re.search(r'<div class="b_caption"[^>]*>(.*?)</div>', block, flags=_re.S)
        snippet = ""
        if m_cap:
            m_p = _re.search(r"<p[^>]*>(.*?)</p>", m_cap.group(1), flags=_re.S)
            snippet = _clean_text(m_p.group(1) if m_p else m_cap.group(1))
        if title and url_real:
            results.append({"title": title, "url": url_real, "snippet": snippet})
    return _dedupe(results)


def _format_results(query: str, results: list[dict]) -> str:
    """把解析出的结果列表格式化为纯文本（首行含搜索词与条数提示）。"""
    lines = [
        f"搜索「{query}」，共获取 {len(results)} 条结果：",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}")
        lines.append(f"URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"摘要: {r['snippet']}")
        lines.append("")  # 每条结果后附换行分隔
    return "\n".join(lines).rstrip("\n")


def search_web(query: str, max_results: int = 5) -> str:
    """搜索网页并返回纯文本结果列表。

    优先使用 DuckDuckGo 免费 HTML 接口（无 API key）；当 DDG 被反爬
    （如本机网络触发 202 anomaly）或未解析到结果时，自动兜底到 Bing
    搜索结果页，保证绝大多数情况下都能返回真实结果。

    Args:
        query: 搜索关键词。
        max_results: 最多返回的结果条数（默认 5）。

    Returns:
        纯文本字符串：首行为搜索词与命中条数提示，随后每条结果为
        “标题\\nURL\\n摘要\\n”并用空行分隔；全部失败返回 'Error: ...'。
    """
    if httpx is None:
        return f"Error: {_IMPORT_ERROR}"

    query = (query or "").strip()
    if not query:
        return "Error: 搜索词为空。"

    last_err = "未知错误"
    # 第一梯队：DuckDuckGo HTML / Lite 接口，失败自动换下一个
    for ep in _ENDPOINTS:
        try:
            resp = httpx.get(
                ep,
                params={"q": query},
                headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.8,en;q=0.5"},
                timeout=15.0,
                follow_redirects=True,
            )
            resp.raise_for_status()
            results = _parse_results(resp.text, str(resp.url))
            results = _dedupe(results)[: max(1, int(max_results))]
            if not results:
                last_err = f"{ep} 未解析到任何结果（可能被反爬或页面结构变化）"
                continue
            return _format_results(query, results)
        except Exception as e:  # noqa: BLE001 - 统一吞异常转错误串
            last_err = f"{type(e).__name__}: {e}"

    # 第二梯队：Bing 兜底
    try:
        results = _search_bing(query)[: max(1, int(max_results))]
        if results:
            return _format_results(query, results)
        last_err = "Bing 未解析到任何结果"
    except Exception as e:  # noqa: BLE001
        last_err = f"Bing: {type(e).__name__}: {e}"

    return f"Error: 搜索失败 —— {last_err}"
