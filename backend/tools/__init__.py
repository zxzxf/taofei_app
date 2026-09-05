"""工具函数包：Agent 可用的全部工具。

架构（阶段 5：工具注册中心）
---------------------------
- ``tools.registry``：全局 ToolRegistry 单例，所有工具在此注册
- 每个工具文件独立自注册（``from .registry import registry; registry.register(...)``）
- 上层通过 ``agent_tools.get_all_tools()`` 或 ``get_tools_by_tag()`` 获取工具列表

向后兼容：原 ``from tools.web_search import search_web`` 等导入方式继续可用。
"""

from .web_search import search_web
from .web_extract import extract_web

__all__ = ["search_web", "extract_web"]
