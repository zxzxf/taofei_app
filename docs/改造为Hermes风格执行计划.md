# Taofei App 后端改造为 Hermes 风格 — 执行计划

> **目标**：将 Taofei App 后端从 ReAct 文本解析模式改造为原生 function calling + token 级流式输出，速度体感接近 Hermes。
> **周期**：分 7 个阶段，预计 3-4 周（全职开发）。
> **创建日期**：2026-09-04

---

## 背景与目标

### 现状
- 工具调用：纯文本 ReAct 格式（Thought / Action / Action Input），正则解析，一次只能调用一个工具
- 流式输出：步骤级 SSE，推送完整 task 快照，跳跃式更新
- 架构：任务式批处理，每个请求开新线程，无前缀缓存
- 模型提供商：DeepSeek / OpenAI 兼容 / Anthropic 兼容，共 3 家

### 目标
- 原生 function calling + 并行工具调用
- Token 级流式输出，首字延迟 < 500ms
- 会话式架构 + 前缀缓存，多轮对话提速 2-3 倍
- 工具注册中心 + 动态 toolsets，支持 50+ 工具
- 多提供商适配器 + 故障转移，可用性大幅提升
- 记忆系统 + 技能学习，从"工具"升级为"代理"

---

## 第一阶段：基础改造 — Function Calling 化（预计 3-4 天）

> 🎯 目标：从 ReAct 文本解析 → 原生 function calling，单步速度提升 50%+

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 1.1 | 新增工具 schema 生成函数 | `backend/agent_tools.py` | 新增 `to_openai_tools()` 将现有 TOOLS 转为 OpenAI function calling 格式 | P0 |
| 1.2 | 重写 Agent 主循环 | `backend/agent_runner.py` | 从 while 循环解析文本 → 调用 `chat.completions.create(tools=..., tool_choice="auto")` | P0 |
| 1.3 | 新增 tool_calls 处理逻辑 | `backend/agent_runner.py` | 解析 `response.message.tool_calls`，执行对应工具，构造 `role: tool` 消息回传 | P0 |
| 1.4 | 精简系统提示词 | `backend/prompts.py` | 删掉大段 ReAct 格式说明，只保留核心指令和约束（从 ~3000 字缩到 ~500 字） | P0 |
| 1.5 | 兼容模型：不支持 function calling 的降级 | `backend/agent_runner.py` | 检测到模型不支持时，自动回退到旧 ReAct 模式 | P1 |
| 1.6 | 单测：验证工具调用 + 最终答案路径 | `backend/tests/` | 至少覆盖：无工具直接回答、单工具调用、多工具调用链 | P1 |

### 验收标准
- [ ] 新的 agent_runner.py 支持 function calling 模式
- [ ] 工具调用准确率从 ~85% → ~99%
- [ ] 单步耗时平均减少 40-60%
- [ ] 旧 ReAct 模式作为 fallback 仍可用

---

## 第二阶段：Token 级流式输出（预计 2-3 天）

> 🎯 目标：从步骤级 SSE → token-by-token 流式，首字延迟从 2-3s → 300-500ms

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 2.1 | 流式 API 调用 | `backend/agent_runner.py` | `stream=True`，迭代 `response` chunks | P0 |
| 2.2 | 流式内容聚合器 | `backend/agent_runner.py` 新增 | 累积 delta，同时组装完整消息（content + tool_calls 分开累加） | P0 |
| 2.3 | SSE 端点改造：新增 token 流接口 | `backend/main.py` | 新增 `/api/agent/token_stream/{task_id}`，推送 `content` delta 和 `tool_call` delta | P0 |
| 2.4 | 工具调用流式检测 | `backend/agent_runner.py` | 边收流边判断是文本回答还是工具调用，提前准备执行 | P1 |
| 2.5 | 工具执行结果流式回显 | `backend/agent_runner.py` | terminal 等长耗时工具实时输出流 | P1 |
| 2.6 | 前端适配：增量渲染 | `frontend-vue/` | 从全量替换 → 逐字追加（前端配合工作） | P0 |

### 验收标准
- [ ] 首字延迟 < 500ms
- [ ] 用户看到持续的"打字机"效果，不再有等待空白
- [ ] 旧 SSE 接口保留兼容（供不支持流式的客户端用）

---

## 第三阶段：并行工具调用（预计 2 天）

> 🎯 目标：支持模型一次输出多个工具调用，并发执行，多工具任务时间折叠

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 3.1 | 工具执行器支持并行 | 新建 `backend/tool_executor.py` | `execute_tools_parallel(calls)` 用线程池并发执行 | P0 |
| 3.2 | 主循环改造：多 tool_call 处理 | `backend/agent_runner.py` | `tool_calls` 是数组，全部执行完再把结果一次性回传 | P0 |
| 3.3 | 错误隔离：单个工具失败不影响其他 | `backend/tool_executor.py` | 每个工具 try/except，失败返回 error 文本 | P0 |
| 3.4 | 并行/串行自动选择 | `backend/agent_runner.py` | 有依赖的工具（后一个输入需要前一个输出）走串行，无依赖的走并行 | P1 |
| 3.5 | 前端展示：多工具同时执行的 UI | `frontend-vue/` | 显示多个工具卡片同时在跑（前端配合工作） | P1 |

### 验收标准
- [ ] 3 个独立工具调用的场景，总耗时从 3×T → ≈ T（最快的那个决定）
- [ ] 工具调用失败不中断对话，模型可以看到错误并重试
- [ ] 单工具调用场景不受影响

---

## 第四阶段：会话式架构 + 前缀缓存（预计 3-4 天）

> 🎯 目标：从 task 式批处理 → session 式长驻对话，多轮对话速度提升 2-3 倍

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 4.1 | 新增 Session 概念 | 新建 `backend/session/session.py` | `Session` 类持有消息列表、agent 实例、模型配置 | P0 |
| 4.2 | Session 管理器（LRU 缓存） | 新建 `backend/session/manager.py` | LRU 缓存 session，空闲超时自动回收 | P0 |
| 4.3 | API 改造：从 task_id → session_id | `backend/main.py` | `/api/chat` 改为传 session_id，消息追加到会话 | P0 |
| 4.4 | 持久化：SQLite 会话表 + 消息表 | `backend/db.py` | 新增 sessions、messages 表，会话结束/定期 flush | P1 |
| 4.5 | 系统提示 + 历史消息缓存优化 | `backend/session/session.py` | 固定前缀不重建，保证 prompt cache 命中率 | P0 |
| 4.6 | 兼容旧 task 模式 | `backend/main.py` | 不传 session_id 时创建临时 session，保持旧接口可用 | P1 |

### 验收标准
- [ ] 多轮对话首字延迟下降 50-70%（前缀缓存命中）
- [ ] 支持对话历史持久化、跨刷新恢复
- [ ] 旧 API 完全兼容

---

## 第五阶段：工具注册中心 + 动态工具集（预计 3 天）

> 🎯 目标：从固定 TOOLS 列表 → 注册中心 + toolsets，扩展性 + 安全性提升

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 5.1 | ToolRegistry 单例 | 新建 `backend/tools/registry.py` | `register()` / `get_definitions()` / `dispatch()` | P0 |
| 5.2 | ToolEntry + check_fn | `backend/tools/registry.py` | 每个工具带启用检查函数，缺依赖/缺配置的不显示 | P0 |
| 5.3 | 工具迁移到自注册模式 | `backend/tools/*.py` | 每个工具文件 `from .registry import registry; registry.register(...)` | P0 |
| 5.4 | Toolsets 系统 | 新建 `backend/toolsets.py` | 工具按场景分组（default / research / coding / all），可组合继承 | P1 |
| 5.5 | 懒加载依赖 | 新建 `backend/tools/lazy_deps.py` | 可选工具的依赖首次使用时才 pip install | P2 |
| 5.6 | 配置驱动的工具启用/禁用 | `backend/db.py` + 设置页 | 用户可以在设置里开关工具 | P1 |

### 验收标准
- [ ] 工具系统支持 50+ 工具而不膨胀 schema（按场景加载）
- [ ] 新增一个工具只需要写一个文件，不用改其他地方
- [ ] 缺依赖的工具自动隐藏，不报错

---

## 第六阶段：多提供商 + 故障转移（预计 4-5 天）

> 🎯 目标：从 3 家固定提供商 → 适配器模式 + 自动故障转移，可用性大幅提升

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 6.1 | Provider 基类（ABC） | 新建 `backend/providers/base.py` | `chat()` / `chat_stream()` / `embed()` 统一接口 | P0 |
| 6.2 | OpenAI 兼容适配器 | `backend/providers/openai_compat.py` | DeepSeek / OpenAI / 自定义端点通用 | P0 |
| 6.3 | Anthropic 适配器 | `backend/providers/anthropic.py` | 消息格式双向转换（OpenAI 格式 ↔ Anthropic Messages） | P1 |
| 6.4 | ErrorClassifier 错误分类器 | 新建 `backend/agent/error_classifier.py` | 20+ 错误类型 → 恢复策略映射 | P1 |
| 6.5 | BackendIdentity 三轴身份 | 新建 `backend/agent/backend_identity.py` | MODEL / CREDENTIAL / ENDPOINT 三级失效判定 | P2 |
| 6.6 | CredentialPool 多凭证池 | 新建 `backend/agent/credential_pool.py` | 同提供商多 Key 轮换，cooldown，dead/ok 状态机 | P2 |
| 6.7 | Fallback 链 | `backend/agent_runner.py` | 主提供商挂了自动切备用，用户无感知 | P1 |
| 6.8 | 提供商注册表 | `backend/providers/registry.py` | 自动探测可用提供商（环境变量 + 配置文件） | P1 |

### 验收标准
- [ ] 支持 10+ 模型提供商
- [ ] 单提供商挂了不中断对话，自动切到备用
- [ ] 多 API Key 负载均衡 + 故障轮换

---

## 第七阶段：记忆 + 技能 + 收尾优化（预计 5-7 天）

> 🎯 目标：补上跨会话学习能力，完成从"工具"到"代理"的跃迁

### 任务清单

| # | 任务 | 改动文件 | 说明 | 优先级 |
|---|------|----------|------|--------|
| 7.1 | FTS5 全文搜索 | `backend/db.py` | 消息表建 FTS5 索引，支持跨会话搜索 | P1 |
| 7.2 | Memory 工具 | 新建 `backend/tools/memory_tool.py` | `memory_save` / `memory_recall` / `memory_forget` | P1 |
| 7.3 | 会话摘要（上下文压缩） | 新建 `backend/agent/context_compressor.py` | 上下文过长时自动 summarize 早期消息 | P1 |
| 7.4 | 技能系统雏形 | 新建 `backend/skills/` | YAML 格式技能，可加载到系统提示中 | P2 |
| 7.5 | 自动技能创建 | 后处理 hook | 复杂任务完成后自动生成技能草稿 | P2 |
| 7.6 | Cron 定时任务（可选） | 新建 `backend/cron/` | 定时触发 agent 执行任务 | P2 |
| 7.7 | 性能基准测试 | `backend/tests/` | 建立 speed/accuracy 基准，防止回归 | P1 |

### 验收标准
- [ ] 跨会话搜索历史消息可用
- [ ] 代理可以主动保存和回忆记忆
- [ ] 长对话自动压缩，不会爆上下文
- [ ] 有性能基准，改动可量化评估

---

## 总览甘特图

```
阶段           第1周       第2周       第3周       第4周
─────────────────────────────────────────────────────────
1. Function Calling   ████░░
2. Token 流式              ███░░
3. 并行工具调用                ██░░
4. 会话式架构                    ████░░
5. 工具注册中心                       ███░░
6. 多提供商 + 故障转移                    █████░
7. 记忆 + 技能 + 优化                         ██████
```

---

## 关键里程碑

| 里程碑 | 完成阶段 | 完成标志 | 速度提升（相对初始） |
|--------|----------|----------|---------------------|
| M1 | 阶段 1 | function calling 跑通 | ~40% 更快 |
| M2 | 阶段 2 | token 级流式可用 | 体感快 2-3 倍（首字延迟从秒级降到百毫秒级） |
| M3 | 阶段 3 | 并行工具调用 | 多工具场景再快 2-3 倍 |
| M4 | 阶段 4 | 会话化 + 缓存 | 多轮对话再快 50-70% |
| M5 | 阶段 7 | 全功能上线 | 综合速度提升 5-10 倍 |

---

## 风险与注意事项

### 主要风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 前端改造进度跟不上 | 流式效果打折扣 | 后端先做好 API，前端逐阶段跟进，旧接口始终兼容 |
| 某些模型不支持 function calling | 功能降级 | 保留 ReAct fallback，自动检测切换 |
| 并行工具调用引入竞态问题 | 工具执行异常 | 线程池 + 结果隔离，每个工具独立 try/except |
| 会话内存泄漏 | 长时间运行内存膨胀 | LRU + 空闲超时回收，定期持久化到 DB |
| 多提供商适配 bug | 某些提供商不可用 | 先做好 2-3 家主力，其余逐步加 |

### 设计原则

1. **向后兼容**：每个阶段都保留旧接口作为 fallback，不一次性破坏现有功能
2. **测试先行**：每阶段先写测试用例，再改代码，保证功能不退化
3. **渐进交付**：每个阶段都有可演示的成果，不是全部做完才能用
4. **最小改动**：能复用的代码尽量复用，不为"优雅"而重构
5. **可观测**：每个关键路径加日志和指标，方便排查性能问题

---

## 参考资料

- Hermes Agent 源码：`E:\20260814\hermes-agent\`
  - `agent/conversation_loop.py` — 对话循环参考
  - `agent/chat_completion_helpers.py` — LLM 调用参考
  - `tools/registry.py` — 工具注册中心参考
  - `agent/error_classifier.py` — 错误分类参考
  - `agent/credential_pool.py` — 多凭证池参考
- OpenAI Function Calling 文档
- Anthropic Messages API 文档
