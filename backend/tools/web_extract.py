"""web_extract.py —— 通用网页正文抽取工具。

- 用 httpx GET 抓取目标 URL（内置 User-Agent、15 秒超时、跟随重定向）；
- 剥离 script / style / nav / footer 等噪音标签后，把剩余 HTML 转换为
  可读纯文本/Markdown；
- 文本超过 max_chars 时截断并在末尾标注已截断的字符数；
- 对外只暴露 extract_web(url, max_chars=8000) -> str：任何情况下都不抛
  异常，出错统一返回 'Error: ...' 开头的字符串。
"""

# ---- 依赖导入容错：优先 html2text，缺失时回退内置实现 ----
try:
    import html2text as _html2text
    _H2T = _html2text.HTML2Text()
    _H2T.ignore_links = False
    _H2T.ignore_images = True
    _H2T.body_width = 0          # 不自动折行，保留原文换行
    _H2T.unicode_snob = True
    _H2T_AVAILABLE = True
except Exception:  # pragma: no cover - 未安装时走自研回退
    _H2T_AVAILABLE = False

try:
    import httpx
except Exception as _import_err:  # pragma: no cover - 容错兜底
    httpx = None
    _IMPORT_ERROR = f"httpx 未安装或导入失败: {_import_err}"
else:
    _IMPORT_ERROR = None

import html.parser as _hp
import re as _re

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 需要整体丢弃的块级噪音标签（连同其内容）
_BLOCK_NOISE = {"script", "style", "nav", "footer", "header", "noscript",
                "iframe", "form", "template", "svg", "aside"}


class _NoiseStripper(_hp.HTMLParser):
    """只负责剥离噪音标签及其内容，输出干净 HTML 字符串。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._out: list[str] = []
        self._skip_depth = 0  # >0 表示正处于应丢弃的标签内部

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self._skip_depth:
            if t in _BLOCK_NOISE:
                self._skip_depth += 1
        elif t in _BLOCK_NOISE:
            self._skip_depth = 1
        else:
            self._out.append(self.get_starttag_text() or f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._skip_depth and tag.lower() not in _BLOCK_NOISE:
            self._out.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._skip_depth:
            if t in _BLOCK_NOISE:
                self._skip_depth -= 1
            return
        if t not in _BLOCK_NOISE:
            self._out.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self._out.append(f"&#{name};")

    def result(self) -> str:
        return "".join(self._out)


class _TextExtractor(_hp.HTMLParser):
    """自研回退：把 HTML 转成带基本结构的纯文本（标题/链接/列表可读）。"""

    _PRETTY_TAGS = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "section", "article", "table", "ul", "ol",
    }
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._pending_newline = False

    def _emit(self, text: str) -> None:
        text = _re.sub(r"\s+", " ", text)
        if not text:
            return
        if self._pending_newline and self._chunks:
            self._chunks.append("\n")
        self._pending_newline = False
        if self._chunks and not self._chunks[-1].endswith(("\n", " ", "\u3000")):
            self._chunks.append(" ")
        self._chunks.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "br":
            self._pending_newline = True
        elif t in self._PRETTY_TAGS or t in self._HEADINGS:
            self._pending_newline = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self._HEADINGS:
            # 标题结束后强制换行，并顺带补一个空行分隔
            if self._chunks and not self._chunks[-1].endswith("\n"):
                self._chunks.append("\n")
            self._chunks.append("\n")
        elif t in {"p", "div", "li", "tr", "blockquote", "section", "article"}:
            self._pending_newline = True

    def handle_data(self, data: str) -> None:
        if data:
            self._emit(data)

    def result(self) -> str:
        return "".join(self._chunks).strip()


def _html_to_text(html_text: str) -> str:
    """把干净 HTML（已剥离噪音标签）转成纯文本。优先 html2text，回退自研实现。"""
    if _H2T_AVAILABLE:
        try:
            text = _H2T.handle(html_text)
            text = _re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
        except Exception:
            pass  # html2text 解析异常时回退自研实现
    parser = _TextExtractor()
    try:
        parser.feed(html_text)
        parser.close()
        return parser.result()
    except Exception:
        return ""


def _strip_noise(html_text: str) -> str:
    """剥离 script/style/nav/footer 等噪音标签（含内容）。"""
    stripper = _NoiseStripper()
    try:
        stripper.feed(html_text)
        stripper.close()
        return stripper.result()
    except Exception:
        return html_text  # 剥离失败时原样返回，交给后面的转换容错


def extract_web(url: str, max_chars: int = 8000) -> str:
    """抓取指定网页并把正文转换为纯文本/Markdown 返回。

    Args:
        url: 目标网页完整 URL（https/http 均可）。
        max_chars: 返回文本的最大字符数（默认 8000）。

    Returns:
        网页正文纯文本；若文本超长则截断并在末尾标注
        “...(已截断 N 字符)”。非 200 状态、抓取失败或解析失败时
        返回 'Error: ...' 字符串，绝不抛异常。
    """
    if httpx is None:
        return f"Error: {_IMPORT_ERROR}"

    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return "Error: 无效的 URL（需以 http:// 或 https:// 开头）。"

    max_chars = max(200, int(max_chars))  # 下限 200，防止 0/负数把输出截成空

    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.8,en;q=0.5"},
            timeout=15.0,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return f"Error: HTTP {resp.status_code} —— {url}"
        # 仅处理文本类响应；其它（图片/PDF 等）明确报错
        ctype = resp.headers.get("content-type", "").lower()
        if ctype and "text/" not in ctype and "html" not in ctype and "xml" not in ctype:
            return f"Error: 非文本内容类型（{ctype or '未知'}），暂不支持解析。"
        raw = resp.text
    except Exception as e:  # noqa: BLE001 - 网络异常统一转错误串
        return f"Error: 抓取失败 —— {type(e).__name__}: {e}"

    if not raw:
        return "Error: 响应内容为空。"

    try:
        clean_html = _strip_noise(raw)
        text = _html_to_text(clean_html)
    except Exception as e:  # noqa: BLE001
        return f"Error: HTML 解析失败 —— {type(e).__name__}: {e}"

    if not text:
        return "Error: 未能从页面解析出可读文本（页面可能为 JS 渲染，正文不在原始 HTML 中）。"

    if len(text) > max_chars:
        truncated = len(text) - max_chars
        text = f"{text[:max_chars]}\n...(已截断 {truncated} 字符)"
    return text
