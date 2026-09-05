# -*- coding: utf-8 -*-
"""ErrorClassifier —— 错误分类器（阶段 6.4）。

把底层 SDK / HTTP 抛出的各种异常统一分类为 **20+ 错误类型**，
并给出**恢复策略**（是否可重试 / 是否应故障转移 / 建议冷却秒数），
供 FallbackChain 与上层日志 / API 使用。

设计
----
- 单一入口：``classify_error(exc, ...)`` 接受任何异常 → ``RecoveryDecision``
- 判定优先级：已分类的 ProviderError > 异常类型名（SDK 类名） > HTTP 状态码 > 消息关键词
- 纯函数、零第三方依赖：不 import openai / anthropic SDK，按类名字符串判定，
  因此打包后无需额外 hiddenimports，任何异常对象都能安全分类。
- 与 providers/base.py 的错误类配合：providers 层在分类后把错误构造为
  ProviderError 子类抛出；本模块只做"分类 + 决策"，不持有 provider 实例。

使用
----
```python
from agent.error_classifier import classify_error
decision = classify_error(exc, provider="deepseek", model="deepseek-chat")
if decision.retryable and decision.should_failover:
    ...  # 切备用 provider
```
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------
# 错误类型码（20+，稳定字符串，用于日志 / 状态上报 / 前端展示）
# ---------------------------------------------------------------

# --- 认证 / 授权 ---
ET_AUTH_INVALID_KEY = "auth_invalid_key"          # API Key 无效
ET_AUTH_EXPIRED = "auth_expired"                  # Key 过期
ET_AUTH_FORBIDDEN = "auth_forbidden"              # 无权限访问该模型/端点
ET_AUTH_QUOTA = "auth_quota_exhausted"            # 配额 / 余额耗尽（429 带 quota 语义）

# --- 限流 ---
ET_RATE_LIMIT_TPM = "rate_limit_tpm"              # 每分钟 token 超限
ET_RATE_LIMIT_RPM = "rate_limit_rpm"              # 每分钟请求超限
ET_RATE_LIMIT = "rate_limit_global"               # 通用限流

# --- 服务端 ---
ET_SERVER_5XX = "server_5xx"                      # 500 / 502 / 504
ET_SERVER_OVERLOADED = "server_overloaded"        # 503 / 529（过载）
ET_SERVER_UNAVAILABLE = "server_unavailable"      # 服务不可用（无明确状态码）

# --- 超时 ---
ET_TIMEOUT_CONNECT = "timeout_connect"            # 连接超时
ET_TIMEOUT_READ = "timeout_read"                  # 读取超时
ET_TIMEOUT = "timeout"                            # 通用超时

# --- 网络 ---
ET_NETWORK_DNS = "network_dns"                    # DNS 解析失败
ET_NETWORK_CONN_REFUSED = "network_conn_refused"  # 连接被拒绝
ET_NETWORK_CONN_RESET = "network_conn_reset"      # 连接被重置
ET_NETWORK_TLS = "network_tls"                    # TLS/SSL 错误
ET_NETWORK = "network"                            # 通用网络错误

# --- 请求 / 参数 ---
ET_BAD_REQUEST = "bad_request"                    # 400 参数错误
ET_CONTEXT_LENGTH = "context_length_exceeded"     # 上下文超长（需压缩）
ET_INVALID_MODEL = "invalid_model"                # 模型不存在 / 不支持
ET_INVALID_API_PATH = "invalid_api_path"          # 端点路径不存在（404）
ET_CONTENT_FILTER = "content_filter"              # 内容被安全策略拦截

# --- 其它 ---
ET_UNKNOWN = "unknown"                            # 无法分类

# 分类器可识别的完整类型清单（用于文档 / 校验）
ALL_ERROR_TYPES = [
    ET_AUTH_INVALID_KEY, ET_AUTH_EXPIRED, ET_AUTH_FORBIDDEN, ET_AUTH_QUOTA,
    ET_RATE_LIMIT_TPM, ET_RATE_LIMIT_RPM, ET_RATE_LIMIT,
    ET_SERVER_5XX, ET_SERVER_OVERLOADED, ET_SERVER_UNAVAILABLE,
    ET_TIMEOUT_CONNECT, ET_TIMEOUT_READ, ET_TIMEOUT,
    ET_NETWORK_DNS, ET_NETWORK_CONN_REFUSED, ET_NETWORK_CONN_RESET,
    ET_NETWORK_TLS, ET_NETWORK,
    ET_BAD_REQUEST, ET_CONTEXT_LENGTH, ET_INVALID_MODEL,
    ET_INVALID_API_PATH, ET_CONTENT_FILTER,
    ET_UNKNOWN,
]


@dataclass
class RecoveryDecision:
    """一次异常的分类结果与恢复建议。"""
    error_type: str = ET_UNKNOWN
    retryable: bool = False          # 同 provider 重试是否可能成功
    should_failover: bool = False    # 是否值得切换到备用 provider
    cooldown_seconds: float = 0.0    # 失败后建议冷却秒数（限流/过载时 > 0）
    message: str = ""
    provider: str = ""
    model: str = ""
    status_code: int | None = None
    retry_after: float | None = None
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "retryable": self.retryable,
            "should_failover": self.should_failover,
            "cooldown_seconds": self.cooldown_seconds,
            "message": self.message[:300],
            "provider": self.provider,
            "model": self.model,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
            "hints": self.hints,
        }


# ---------------------------------------------------------------
# 内部：从 ProviderError 子类直接分类（无需再看 SDK 异常）
# ---------------------------------------------------------------
def _classify_provider_error(exc: Exception, decision: RecoveryDecision) -> RecoveryDecision:
    """如果异常已经是我们的 ProviderError 子类，直接按类型分类。"""
    exc_name = type(exc).__name__
    provider = getattr(exc, "provider", "") or decision.provider
    model = getattr(exc, "model", "") or decision.model

    if exc_name == "AuthError":
        msg_l = str(exc).lower()
        if any(k in msg_l for k in ("quota", "余额", "insufficient", "billing", "payment")):
            decision.error_type = ET_AUTH_QUOTA
            decision.retryable = False
            decision.should_failover = True  # 换一个 provider 可能还有配额
        elif any(k in msg_l for k in ("expired", "过期")):
            decision.error_type = ET_AUTH_EXPIRED
            decision.retryable = False
            decision.should_failover = True
        elif any(k in msg_l for k in ("forbidden", "permission", "没有权限", "无权限", "not allowed")):
            decision.error_type = ET_AUTH_FORBIDDEN
            decision.retryable = False
            decision.should_failover = True
        else:
            decision.error_type = ET_AUTH_INVALID_KEY
            decision.retryable = False
            decision.should_failover = True  # 备用 key / provider 可能有效
        decision.hints.append("检查 API Key 是否正确、是否过期、是否有该模型权限")

    elif exc_name == "RateLimitError":
        decision.error_type = ET_RATE_LIMIT
        decision.retryable = True
        decision.should_failover = True
        decision.retry_after = getattr(exc, "retry_after", None)
        decision.cooldown_seconds = max(decision.retry_after or 0.0, 10.0)
        decision.hints.append("限流：可稍后重试，或切换备用 provider")

    elif exc_name == "ServerError":
        decision.error_type = ET_SERVER_5XX
        decision.retryable = True
        decision.should_failover = True
        decision.cooldown_seconds = 5.0
        decision.hints.append("服务端错误：可重试或故障转移")

    elif exc_name == "TimeoutError":
        decision.error_type = ET_TIMEOUT
        decision.retryable = True
        decision.should_failover = True
        decision.cooldown_seconds = 2.0
        decision.hints.append("请求超时：可重试或切备用")

    elif exc_name == "NetworkError":
        decision.error_type = ET_NETWORK
        decision.retryable = True
        decision.should_failover = True
        decision.cooldown_seconds = 2.0
        decision.hints.append("网络错误：可重试或切备用")

    elif exc_name == "ContextLengthError":
        decision.error_type = ET_CONTEXT_LENGTH
        decision.retryable = False
        decision.should_failover = False  # 换 provider 没用，需压缩上下文
        decision.hints.append("上下文超长：需压缩历史或增大模型上下文窗口")

    elif exc_name == "BadRequestError":
        decision.error_type = ET_BAD_REQUEST
        decision.retryable = False
        decision.should_failover = False
        decision.hints.append("请求参数错误：修正请求，勿重试")

    else:
        decision.error_type = ET_UNKNOWN
        decision.retryable = getattr(exc, "retryable", False)
        decision.should_failover = decision.retryable

    decision.provider = provider
    decision.model = model
    return decision


# ---------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------
def classify_error(exc: Exception, provider: str = "", model: str = "") -> RecoveryDecision:
    """把任意异常分类为 RecoveryDecision。

    兼容：ProviderError 子类 / openai SDK / anthropic SDK / httpx /
    requests / urllib / 普通异常。按类型名 + 状态码 + 消息关键词判定。
    """
    decision = RecoveryDecision(
        message=str(exc)[:500], provider=provider, model=model,
    )
    exc_name = type(exc).__name__
    msg = str(exc)
    msg_l = msg.lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

    # 1) 已是我们的 ProviderError 子类
    if exc_name in (
        "AuthError", "RateLimitError", "ServerError", "TimeoutError",
        "NetworkError", "BadRequestError", "ContextLengthError", "ProviderError",
    ):
        return _classify_provider_error(exc, decision)

    # 2) HTTP 状态码优先（openai/anthropic SDK 异常带 status_code）
    if isinstance(status, int):
        decision.status_code = status
        decision = _classify_by_status(status, decision, exc_name, msg_l)

    # 3) SDK 异常类型名 / 关键词兜底
    else:
        decision = _classify_by_name(exc_name, msg_l, decision)

    decision.provider = provider
    decision.model = model
    return decision


def _classify_by_status(status: int, d: RecoveryDecision,
                        exc_name: str, msg_l: str) -> RecoveryDecision:
    """按 HTTP 状态码分类（SDK 异常的 status_code 属性）。"""
    if status == 401:
        d.error_type = ET_AUTH_INVALID_KEY
        d.retryable, d.should_failover = False, True
        if "quota" in msg_l or "insufficient" in msg_l or "余额" in msg_l:
            d.error_type = ET_AUTH_QUOTA
        d.hints.append("401：API Key 无效或无权限")
    elif status == 403:
        d.error_type = ET_AUTH_FORBIDDEN
        d.retryable, d.should_failover = False, True
        d.hints.append("403：无权访问该资源")
    elif status == 404:
        if "model" in msg_l or "model not found" in msg_l:
            d.error_type = ET_INVALID_MODEL
            d.retryable, d.should_failover = False, False
            d.hints.append("404：模型不存在，检查 model 名称")
        else:
            d.error_type = ET_INVALID_API_PATH
            d.retryable, d.should_failover = False, False
            d.hints.append("404：API 路径不存在，检查 base_url")
    elif status == 429:
        d.retryable, d.should_failover = True, True
        retry_after = None
        m = re.search(r"retry[-_ ]?after[^\d]*(\d+)", msg_l)
        if m:
            retry_after = float(m.group(1))
        d.retry_after = retry_after
        d.cooldown_seconds = max(retry_after or 0.0, 10.0)
        if "tokens" in msg_l or "tpm" in msg_l:
            d.error_type = ET_RATE_LIMIT_TPM
            d.hints.append("429：每分钟 token 数超限")
        elif "request" in msg_l or "rpm" in msg_l:
            d.error_type = ET_RATE_LIMIT_RPM
            d.hints.append("429：每分钟请求数超限")
        else:
            d.error_type = ET_RATE_LIMIT
            if "quota" in msg_l or "insufficient" in msg_l or "余额" in msg_l:
                d.error_type = ET_AUTH_QUOTA
                d.retryable = False
                d.should_failover = True
            d.hints.append("429：限流或配额不足")
    elif status in (500, 502, 504):
        d.error_type = ET_SERVER_5XX
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 5.0
        d.hints.append(f"{status}：服务端错误")
    elif status in (503, 529):
        d.error_type = ET_SERVER_OVERLOADED
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 15.0
        d.hints.append(f"{status}：服务过载")
    elif status == 400:
        d.retryable, d.should_failover = False, False
        if "context" in msg_l and ("length" in msg_l or "token" in msg_l):
            d.error_type = ET_CONTEXT_LENGTH
            d.hints.append("400：上下文超长")
        elif "content" in msg_l and ("filter" in msg_l or "policy" in msg_l or "safety" in msg_l):
            d.error_type = ET_CONTENT_FILTER
            d.hints.append("400：内容被安全策略拦截")
        else:
            d.error_type = ET_BAD_REQUEST
            d.hints.append("400：请求参数错误")
    else:
        # 未识别状态码 → 交给类型名/关键词判定
        d = _classify_by_name(exc_name, msg_l, d)
        if d.error_type == ET_UNKNOWN and status >= 500:
            d.error_type = ET_SERVER_5XX
            d.retryable, d.should_failover = True, True
    return d


def _classify_by_name(exc_name: str, msg_l: str,
                      d: RecoveryDecision) -> RecoveryDecision:
    """按 SDK 异常类名 + 消息关键词分类。"""
    # --- 认证 ---
    if "Authentication" in exc_name or "Unauthorized" in exc_name \
            or "401" in msg_l or ("api key" in msg_l and ("invalid" in msg_l or "incorrect" in msg_l)):
        d.error_type = ET_AUTH_INVALID_KEY
        d.retryable, d.should_failover = False, True
        d.hints.append("认证失败：检查 API Key")
    # --- 限流 ---
    elif "RateLimit" in exc_name or "429" in msg_l:
        d.error_type = ET_RATE_LIMIT
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 10.0
        d.hints.append("限流：稍后重试或切备用")
    # --- 权限 ---
    elif "Permission" in exc_name or "Forbidden" in exc_name or "403" in msg_l:
        d.error_type = ET_AUTH_FORBIDDEN
        d.retryable, d.should_failover = False, True
        d.hints.append("无权限：检查账号权限")
    # --- 服务端 ---
    elif "InternalServer" in exc_name or "500" in msg_l or "502" in msg_l or "504" in msg_l:
        d.error_type = ET_SERVER_5XX
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 5.0
    elif "Overloaded" in exc_name or "529" in msg_l or "503" in msg_l or "overloaded" in msg_l:
        d.error_type = ET_SERVER_OVERLOADED
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 15.0
    elif "ServiceUnavailable" in exc_name:
        d.error_type = ET_SERVER_UNAVAILABLE
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 10.0
    # --- 超时 ---
    elif "Timeout" in exc_name or "timed out" in msg_l or "timeout" in msg_l:
        d.error_type = ET_TIMEOUT
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 2.0
        if "connect" in msg_l:
            d.error_type = ET_TIMEOUT_CONNECT
        elif "read" in msg_l:
            d.error_type = ET_TIMEOUT_READ
    # --- 网络 ---
    elif "APIConnection" in exc_name or "Connection" in exc_name \
            or "ConnectError" in exc_name or "network" in msg_l:
        d.error_type = ET_NETWORK
        d.retryable, d.should_failover = True, True
        d.cooldown_seconds = 2.0
        if "dns" in msg_l or "name or service" in msg_l or "getaddrinfo" in msg_l:
            d.error_type = ET_NETWORK_DNS
        elif "refused" in msg_l:
            d.error_type = ET_NETWORK_CONN_REFUSED
        elif "reset" in msg_l:
            d.error_type = ET_NETWORK_CONN_RESET
        elif "ssl" in msg_l or "tls" in msg_l or "certificate" in msg_l:
            d.error_type = ET_NETWORK_TLS
    # --- 请求参数 ---
    elif "BadRequest" in exc_name or "400" in msg_l or "InvalidRequest" in exc_name:
        d.retryable, d.should_failover = False, False
        if "context" in msg_l and ("length" in msg_l or "token" in msg_l or "too long" in msg_l):
            d.error_type = ET_CONTEXT_LENGTH
        elif "model" in msg_l and ("not found" in msg_l or "不存在" in msg_l):
            d.error_type = ET_INVALID_MODEL
        elif "not found" in msg_l or "404" in msg_l:
            d.error_type = ET_INVALID_API_PATH
        else:
            d.error_type = ET_BAD_REQUEST
    # --- 内容策略 ---
    elif "ContentPolicy" in exc_name or "content_filter" in msg_l or "safety" in msg_l:
        d.error_type = ET_CONTENT_FILTER
        d.retryable, d.should_failover = False, False
    # --- 未识别：保守视为可重试服务端问题 ---
    else:
        d.error_type = ET_UNKNOWN
        # 普通网络异常（requests/urllib 抛出的裸异常）
        if any(t in exc_name for t in ("URLError", "HTTPError", "RemoteProtocolError", "ReadError")):
            d.error_type = ET_NETWORK
            d.retryable, d.should_failover = True, True
            d.cooldown_seconds = 2.0
        else:
            d.retryable = False
            d.should_failover = False
    return d


# ---------------------------------------------------------------
# 便捷 helper
# ---------------------------------------------------------------
def is_retryable(exc: Exception) -> bool:
    """快速判断异常是否可重试（供 try/except 使用）。"""
    return classify_error(exc).retryable


def should_failover(exc: Exception) -> bool:
    """快速判断异常是否值得触发故障转移。"""
    return classify_error(exc).should_failover


def describe(exc: Exception) -> str:
    """给日志用的一句话描述：error_type (retryable=?) - message。"""
    d = classify_error(exc)
    return f"[{d.error_type}] retryable={d.retryable} failover={d.should_failover} {d.message[:200]}"


if __name__ == "__main__":
    # 自检：分类几个典型异常
    class _FakeAuth(Exception):
        pass

    class _FakeRate(Exception):
        pass

    samples = [
        _FakeAuth("Incorrect API key provided: sk-xxx"),
        _FakeRate("Rate limit reached for requests"),
        TimeoutError("Request timed out after 60s"),
        ConnectionError("Connection refused"),
        ValueError("random stuff"),
    ]
    for s in samples:
        d = classify_error(s)
        print(f"{type(s).__name__:20s} -> {d.error_type:24s} retryable={d.retryable} failover={d.should_failover}")
