"""工具函数包：为 agent 提供自包含的 web 搜索与网页正文抽取能力。"""

from .web_search import search_web
from .web_extract import extract_web

__all__ = ["search_web", "extract_web"]
