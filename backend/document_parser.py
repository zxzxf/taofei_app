"""文档解析模块。

职责：
- 根据文件扩展名把文档内容提取为纯文本，供后续分块与向量化使用。
- 支持常见文本/代码文件与 PDF。
"""

from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".vue", ".html", ".css", ".json", ".yaml", ".yml", ".xml", ".csv",
    ".log", ".ini", ".cfg", ".sh", ".ps1", ".bat", ".toml",
}


def parse_document(file_path: str | Path) -> str:
    """读取文件并返回纯文本；不支持的格式或读取失败返回空字符串。"""
    p = Path(file_path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()

    if suffix in TEXT_EXTENSIONS:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    if suffix == ".pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(p))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        except Exception:
            return ""

    return ""
