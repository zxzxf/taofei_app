"""工具注册中心。

设计原则
--------
- **单例模式**：``registry = ToolRegistry()`` 全局唯一，所有工具在模块加载时自动注册
- **自注册**：每个工具文件 ``from .registry import registry; registry.register(...)``
- **check_fn**：每个工具可选启用检查函数，缺依赖/缺配置时不注册（对上层透明隐藏）
- **toolsets**：工具按 tag 分组，上层按需拉取不同场景的工具集（default / research / all）
- **向后兼容**：``agent_tools.TOOLS`` 继续可用，内部改为从 registry 读取

使用方式
--------
在工具模块中::

    from .registry import registry

    def my_tool_impl(workspace_path, arg1, arg2=None):
        ...
        return {"observation": "...", "error": ""}

    registry.register(
        name="my_tool",
        description="工具描述",
        parameters={
            "type": "object",
            "properties": {"arg1": {"type": "string", "description": "参数1"},
                           "arg2": {"type": "integer", "description": "参数2"}},
            "required": ["arg1"],
        },
        handler=my_tool_impl,
        tags=["default"],
    )
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional


class ToolRegistry:
    """工具注册中心单例。"""

    def __init__(self) -> None:
        # name -> {name, description, parameters, handler, tags, check_fn, _available}
        self._tools: dict[str, dict] = {}
        self._loaded = False  # 是否已执行惰性加载

    # ---------------------------------------------------------------
    # 注册
    # ---------------------------------------------------------------
    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[..., Any],
        tags: Optional[list[str]] = None,
        check_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        """注册一个工具。

        name 重复时后者覆盖前者（方便测试 mock / 热替换）。
        """
        if not name or not callable(handler):
            return
        self._tools[name] = {
            "name": name,
            "description": description or "",
            "parameters": parameters or {"type": "object", "properties": {}, "required": []},
            "handler": handler,
            "tags": list(tags) if tags else ["default"],
            "check_fn": check_fn,
            "_available": None,  # None=未检测, True=可用, False=不可用
        }

    def unregister(self, name: str) -> None:
        """移除一个工具（主要供测试用）。"""
        self._tools.pop(name, None)

    # ---------------------------------------------------------------
    # 可用性检测（惰性，首次调用时执行一次）
    # ---------------------------------------------------------------
    def _is_available(self, entry: dict) -> bool:
        if entry["_available"] is not None:
            return entry["_available"]
        if entry["check_fn"] is None:
            entry["_available"] = True
            return True
        try:
            entry["_available"] = bool(entry["check_fn"]())
        except Exception:
            entry["_available"] = False
        return entry["_available"]

    # ---------------------------------------------------------------
    # 查询
    # ---------------------------------------------------------------
    def get_tools(self, toolset: str = "default") -> list[dict]:
        """返回指定 toolset 的工具列表（TOOLS 格式：{name, description, parameters, handler}）。

        toolset 取值：
        - ``"default"``：默认工具集（不含研究/实验性质工具）
        - ``"research"``：联网调研工具（web_search + web_extract 等）
        - ``"all"``：全部可用工具
        - 其他字符串：匹配 tag
        """
        self._ensure_loaded()
        result = []
        for name, entry in self._tools.items():
            if not self._is_available(entry):
                continue
            tags = entry["tags"]
            if toolset == "all" or toolset in tags:
                result.append({
                    "name": entry["name"],
                    "description": entry["description"],
                    "parameters": entry["parameters"],
                    "handler": entry["handler"],
                })
        return result

    def get_openai_functions(self, toolset: str = "default") -> list[dict]:
        """返回 OpenAI function calling 格式的工具定义（不含 handler）。"""
        tools = self.get_tools(toolset)
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    def has_tool(self, name: str) -> bool:
        """检查某个工具是否存在且可用。"""
        self._ensure_loaded()
        entry = self._tools.get(name)
        if not entry:
            return False
        return self._is_available(entry)

    def dispatch(
        self,
        name: str,
        workspace_path: str | None,
        args: dict,
        **kwargs,
    ) -> dict:
        """执行工具。

        返回 ``{"observation": str, "error": str}`` 格式，与现有 execute_tool 兼容。
        工具不存在时返回 error。
        """
        self._ensure_loaded()
        entry = self._tools.get(name)
        if not entry:
            return {"observation": "", "error": f"未知工具：{name}"}
        if not self._is_available(entry):
            return {"observation": "", "error": f"工具 {name} 当前不可用（缺依赖或配置）"}
        if not isinstance(args, dict):
            args = {}
        try:
            result = entry["handler"](workspace_path, args, **kwargs)
        except Exception as exc:
            return {"observation": "", "error": f"工具 {name} 执行异常：{type(exc).__name__}: {exc}"}

        # 归一化返回值：支持 dict{observation,error} 或直接返回 str
        if isinstance(result, dict):
            obs = str(result.get("observation", ""))
            err = str(result.get("error", ""))
            return {"observation": obs, "error": err}
        return {"observation": str(result or ""), "error": ""}

    # ---------------------------------------------------------------
    # 惰性加载所有工具模块（首次查询时触发）
    # ---------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        # 导入 tools 包下所有子模块，触发各自的 register 调用
        self._import_all_tools()

    def _import_all_tools(self) -> None:
        """导入 tools/ 目录下所有子模块（排除 _ 开头的内部模块）。"""
        import importlib
        import os

        tools_dir = os.path.dirname(__file__)
        for fname in os.listdir(tools_dir):
            if not fname.endswith(".py"):
                continue
            mod_name = fname[:-3]
            if mod_name.startswith("_") or mod_name == "registry":
                continue
            try:
                importlib.import_module(f"tools.{mod_name}")
            except Exception:
                # 单个工具模块导入失败不影响其他工具
                # （缺依赖的工具会在 check_fn 阶段过滤，这里是更底层的导入错误）
                pass


# 全局单例
registry = ToolRegistry()


# ---------------------------------------------------------------
# 工具函数装饰器（可选语法糖）
# ---------------------------------------------------------------
def tool(
    name: str,
    description: str,
    parameters: dict,
    tags: Optional[list[str]] = None,
    check_fn: Optional[Callable[[], bool]] = None,
):
    """工具函数装饰器，注册到全局 registry。

    被装饰函数签名约定：``def handler(workspace_path, args_dict, **kwargs)``
    返回 ``{"observation": str, "error": str}`` 或字符串。
    """
    def decorator(fn: Callable) -> Callable:
        registry.register(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            tags=tags,
            check_fn=check_fn,
        )
        return fn
    return decorator
