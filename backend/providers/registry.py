"""提供商注册表（阶段 6：多提供商）。

自动探测可用的提供商（从环境变量 / 配置文件 / DB 预设），
创建对应的 provider 实例，供上层使用。

设计
----
- **自动探测**：按环境变量判断哪些提供商有 API Key
- **预设管理**：从 model_presets 表读取用户配置的模型预设
- **Fallback 链构建**：根据优先级自动组装 FallbackChain
- **懒加载**：provider 实例按需创建，不浪费连接

使用
----
```python
from providers.registry import ProviderRegistry

registry = ProviderRegistry()
# 从预设 ID 获取 provider
provider = registry.get_provider(preset_id="xxx")
# 构建 fallback 链
chain = registry.build_fallback_chain(["preset1", "preset2"])
```
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

from .base import BaseProvider
from .openai_compat import OpenAICompatProvider
from .fallback_chain import FallbackChain

try:
    from .anthropic import AnthropicProvider
    HAS_ANTHROPIC_PROVIDER = True
except Exception:
    HAS_ANTHROPIC_PROVIDER = False
    AnthropicProvider = None  # type: ignore


@dataclass
class ProviderConfig:
    """一个提供商的配置。"""
    id: str
    name: str
    provider_type: str  # "openai_compat" / "anthropic"
    model: str
    api_key: str = ""
    base_url: str = ""
    timeout: float = 120.0
    priority: int = 0  # 数字越小优先级越高
    enabled: bool = True


class ProviderRegistry:
    """提供商注册表。

    单例模式（通过 ``get_instance()`` 获取），也可以直接实例化。
    """

    _instance: "ProviderRegistry | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProviderRegistry":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._configs: dict[str, ProviderConfig] = {}
        self._providers: dict[str, BaseProvider] = {}
        self._lock = threading.Lock()
        self._loaded_from_db = False

    # -----------------------------------------------------------
    # 配置管理
    # -----------------------------------------------------------
    def register_config(self, config: ProviderConfig) -> None:
        """注册一个提供商配置。"""
        with self._lock:
            self._configs[config.id] = config

    def register_from_dict(self, config_dict: dict[str, Any]) -> None:
        """从 dict 注册配置。"""
        cfg = ProviderConfig(
            id=config_dict["id"],
            name=config_dict.get("name", config_dict["id"]),
            provider_type=config_dict.get("provider_type", "openai_compat"),
            model=config_dict.get("model", ""),
            api_key=config_dict.get("api_key", ""),
            base_url=config_dict.get("base_url", ""),
            timeout=float(config_dict.get("timeout", 120.0)),
            priority=int(config_dict.get("priority", 0)),
            enabled=bool(config_dict.get("enabled", True)),
        )
        self.register_config(cfg)

    def auto_discover_env(self) -> list[str]:
        """从环境变量自动探测可用提供商。

        返回新增的配置 ID 列表。
        """
        added: list[str] = []

        # OpenAI
        if os.environ.get("OPENAI_API_KEY"):
            self.register_from_dict({
                "id": "openai",
                "name": "OpenAI",
                "provider_type": "openai_compat",
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "api_key": os.environ["OPENAI_API_KEY"],
                "base_url": os.environ.get("OPENAI_BASE_URL", ""),
                "priority": 10,
            })
            added.append("openai")

        # DeepSeek
        if os.environ.get("DEEPSEEK_API_KEY"):
            self.register_from_dict({
                "id": "deepseek",
                "name": "DeepSeek",
                "provider_type": "openai_compat",
                "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "api_key": os.environ["DEEPSEEK_API_KEY"],
                "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                "priority": 0,  # 默认主提供商
            })
            added.append("deepseek")

        # Anthropic
        if os.environ.get("ANTHROPIC_API_KEY") and HAS_ANTHROPIC_PROVIDER:
            self.register_from_dict({
                "id": "anthropic",
                "name": "Anthropic",
                "provider_type": "anthropic",
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                "api_key": os.environ["ANTHROPIC_API_KEY"],
                "base_url": os.environ.get("ANTHROPIC_BASE_URL", ""),
                "priority": 20,
            })
            added.append("anthropic")

        # 兼容旧变量：TAOFEI_API_KEY / TAOFEI_BASE_URL
        if os.environ.get("TAOFEI_API_KEY") and "deepseek" not in added:
            self.register_from_dict({
                "id": "taofei_default",
                "name": "Default",
                "provider_type": "openai_compat",
                "model": os.environ.get("TAOFEI_MODEL", "deepseek-chat"),
                "api_key": os.environ["TAOFEI_API_KEY"],
                "base_url": os.environ.get("TAOFEI_BASE_URL", "https://api.deepseek.com/v1"),
                "priority": 5,
            })
            added.append("taofei_default")

        return added

    def load_from_db(self) -> None:
        """从数据库 model_presets 表加载配置（presets 全部注册为候选）。"""
        try:
            import db
            data = db.load_presets()  # {presets: [{id,name,provider,model,base_url,api_key}], active_id}
            presets = data.get("presets", []) if isinstance(data, dict) else []
            for idx, p in enumerate(presets):
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id", ""))
                if not pid:
                    continue
                provider_name = str(p.get("provider", "")).lower()
                self.register_from_dict({
                    "id": pid,
                    "name": p.get("name") or pid,
                    # DB 存的是 provider 名称（deepseek/openai/anthropic/...），映射到 provider_type
                    "provider_type": "anthropic" if provider_name == "anthropic" else "openai_compat",
                    "model": p.get("model", ""),
                    "api_key": p.get("api_key", ""),
                    "base_url": p.get("base_url", ""),
                    "priority": idx,  # 列表顺序即优先级
                    "enabled": True,
                })
            self._loaded_from_db = True
        except Exception:
            # DB 不可用时静默失败
            pass

    # -----------------------------------------------------------
    # Provider 获取
    # -----------------------------------------------------------
    def get_provider(self, preset_id: str | None = None) -> BaseProvider | None:
        """获取一个 provider 实例（懒加载创建）。

        - preset_id 为 None 时返回优先级最高的可用 provider
        - 找不到返回 None
        """
        # 还没从 DB 加载过，先加载
        if not self._loaded_from_db:
            self.load_from_db()

        # 没指定 ID，返回优先级最高的
        if not preset_id:
            best = self._best_config()
            if best is None:
                # 试试环境变量自动探测
                if self.auto_discover_env():
                    best = self._best_config()
            if best is None:
                return None
            preset_id = best.id

        # 已有实例直接返回
        with self._lock:
            if preset_id in self._providers:
                return self._providers[preset_id]

        # 根据配置创建
        cfg = self._configs.get(preset_id)
        if cfg is None or not cfg.enabled:
            return None

        try:
            provider = self._create_provider(cfg)
        except Exception:
            return None

        with self._lock:
            self._providers[preset_id] = provider
        return provider

    def _best_config(self) -> ProviderConfig | None:
        """返回优先级最高的可用配置。"""
        enabled = [c for c in self._configs.values() if c.enabled and c.api_key]
        if not enabled:
            return None
        enabled.sort(key=lambda c: c.priority)
        return enabled[0]

    def _create_provider(self, cfg: ProviderConfig) -> BaseProvider:
        """根据配置创建 provider 实例。"""
        if cfg.provider_type == "anthropic":
            if not HAS_ANTHROPIC_PROVIDER:
                raise RuntimeError("anthropic SDK 未安装")
            return AnthropicProvider(
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url or None,
                timeout=cfg.timeout,
            )
        else:
            # 默认 openai_compat
            return OpenAICompatProvider(
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url or None,
                timeout=cfg.timeout,
            )

    # -----------------------------------------------------------
    # FallbackChain 构建
    # -----------------------------------------------------------
    def build_fallback_chain(self, preset_ids: list[str] | None = None,
                             exclude_ids: list[str] | None = None) -> FallbackChain | None:
        """构建 FallbackChain。

        - preset_ids 指定优先级顺序；为 None 时按所有可用配置的 priority 排序
        - exclude_ids 排除指定配置（如当前正在使用的主 provider）
        """
        exclude = set(exclude_ids or [])
        providers: list[BaseProvider] = []

        if preset_ids:
            for pid in preset_ids:
                if pid in exclude:
                    continue
                p = self.get_provider(pid)
                if p is not None:
                    providers.append(p)
        else:
            # 按优先级排序
            configs = sorted(
                [c for c in self._configs.values() if c.enabled and c.api_key and c.id not in exclude],
                key=lambda c: c.priority,
            )
            for cfg in configs:
                p = self.get_provider(cfg.id)
                if p is not None:
                    providers.append(p)

        if not providers:
            return None

        return FallbackChain(providers)

    # -----------------------------------------------------------
    # 工具方法
    # -----------------------------------------------------------
    def list_configs(self) -> list[dict]:
        """列出所有配置（不含 API Key）。"""
        result = []
        for cfg in self._configs.values():
            result.append({
                "id": cfg.id,
                "name": cfg.name,
                "provider_type": cfg.provider_type,
                "model": cfg.model,
                "base_url": cfg.base_url,
                "priority": cfg.priority,
                "enabled": cfg.enabled,
            })
        return result

    def health_check_all(self) -> list[dict]:
        """对所有启用的 provider 做健康检查。"""
        results = []
        for cfg in self._configs.values():
            if not cfg.enabled:
                continue
            p = self.get_provider(cfg.id)
            if p is None:
                results.append({"id": cfg.id, "name": cfg.name, "ok": False, "error": "创建失败"})
                continue
            hc = p.health_check()
            results.append({
                "id": cfg.id,
                "name": cfg.name,
                "ok": hc["ok"],
                "latency_ms": hc["latency_ms"],
                "error": hc["error"],
            })
        return results

    def reset(self) -> None:
        """清空所有配置和实例（测试用）。"""
        with self._lock:
            self._configs.clear()
            self._providers.clear()
            self._loaded_from_db = False
