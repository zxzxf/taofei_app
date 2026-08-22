# CrewAI Workbench — AI 智能体工作台

基于 **CrewAI + FastAPI + Web 前端** 的最小可运行桌面应用项目，支持打包为单个 exe。

## 功能

- 💬 输入任意主题，自动创建「研究员 + 分析师」双 Agent 顺序协作任务
- 📊 左侧导航 + 模板卡片 + 任务历史，仿 IDE 工作台界面
- 📄 结果实时展示（Markdown 渲染，可一键复制）
- 📦 支持 PyInstaller 打包为独立 exe

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端框架 | **FastAPI** + **Uvicorn** | 异步 Web 框架 + ASGI 服务器，提供任务 API / 日志 API / WebSocket / 静态页面 |
| 数据校验 | **Pydantic** | 请求/响应模型与日志记录校验 |
| AI 智能体 | **CrewAI** | Agent / Crew / Process / Task 多智能体协作框架 |
| LLM 兼容层 | **LangChain**（langchain-openai / langchain-core） | crewai.LLM 缺失时基于 ChatOpenAI 的兼容适配器 |
| LLM 直连 | **httpx** | Anthropic Messages API 兼容端点原生调用（阿里云 MaaS、DeepSeek /anthropic） |
| 持久化 | **SQLite**（标准库 sqlite3） | 模型配置、预设、工作区、技能、工作流、任务历史，零 ORM 依赖 |
| 配置管理 | **python-dotenv** | 读取 .env 环境变量（API Key 等） |
| 工作流引擎 | 自研 **wf_engine** + **PyYAML** | DAG 解析、变量池、节点执行器、Dify DSL 导入 |
| 实时通信 | **WebSocket**（FastAPI） | 任务日志流式推送（ws_manager.py） |
| 并发 | threading / asyncio / concurrent.futures | 后台任务、线程安全日志缓冲、线程池节点执行 |
| 前端框架 | **Vue 3** + **Vue Router 4** | 8 个页面（Task/Agents/Chat/Dashboard/Analysis/Integration/Knowledge/Settings） |
| 前端构建 | **Vite 6** + **@vitejs/plugin-vue** | 构建输出到根目录 frontend/ |
| 桌面端 | **Electron 33** + **electron-builder 25** | 原生窗口壳，NSIS 安装包，自动拉起/清理后端进程 |
| 打包 | **PyInstaller** | 后端 + 前端静态资源打包为独立 exe |
| 模型提供商 | **DeepSeek**（默认）/ OpenAI 兼容 / Anthropic 兼容 | 多预设切换，支持自定义 base_url 与 API Key |
| 脚本工具 | PowerShell（browse_directory.ps1） | Windows 目录浏览辅助 |

## 项目结构

```
crewai_app/
├── backend/
│   ├── main.py          # FastAPI 后端：crewAI 封装 + 任务 API + 静态页面
│   ├── agent_runner.py  # Agent 任务执行器（ReAct 循环）
│   ├── agent_tools.py   # Agent 工具集（文件/目录/HTTP 等本地工具）
│   ├── db.py            # SQLite 持久化层（模型配置/预设/工作区/技能/工作流）
│   ├── ws_manager.py    # WebSocket 连接管理（日志实时推送）
│   └── wf_engine/       # 自研工作流引擎（DSL 解析 + DAG 执行 + 变量池）
├── frontend-vue/        # Vue 3 + Vite 前端源码
│   ├── src/views/       # 8 个页面（Task/Agents/Chat/Dashboard/Analysis/Integration/Knowledge/Settings）
│   ├── src/router/index.js
│   ├── src/styles/global.css
│   ├── vite.config.js   # 构建输出 → 项目根 frontend/
│   └── package.json
├── frontend/            # 前端构建产物（npm run build 生成，不入库，.gitignore）
├── build/
│   └── CrewAIWorkbench.spec   # PyInstaller 打包配置
├── desktop/             # Electron 桌面客户端
│   ├── main.js          # 主进程：拉起后端 + 端口解析 + health 轮询 + 窗口管理
│   ├── preload.js
│   ├── launcher.js
│   ├── package.json     # electron-builder 配置（NSIS 安装包）
│   └── build-desktop.bat# 一键打包：前端构建 → PyInstaller 后端 → Electron 安装包
├── requirements.txt
└── .env.example         # 配置模板（复制为 .env 并填入 API Key）
```

## 快速开始（开发模式）

前后端分离开发（两个服务，Vite 负责热更新，Uvicorn 提供 API）：

```bash
# 1. 后端（终端 1）
cd taofei_app
copy .env.example .env   # 编辑 .env，填入 DEEPSEEK_API_KEY
.venv\Scripts\python.exe backend\main.py
# 监听 http://127.0.0.1:8000

# 2. 前端（终端 2）
cd frontend-vue
npm install   # 首次
npm run dev   # 监听 http://localhost:5173，已通过 vite.config.server.proxy 转发 /api 到 8000
```

访问 http://localhost:5173 即可使用。

## 前端构建（供后端打包使用）

Vite 构建输出到项目根 `frontend/`，后端会把它作为静态资源目录，PyInstaller 打包时也会收集此目录。

```bash
cd frontend-vue
npm install   # 首次
npm run build
# 产物：../frontend/index.html  ../frontend/assets/*.{js,css}
```

> 注意：`frontend/` 已加入 `.gitignore`，不会提交到仓库。桌面打包脚本 `build-desktop.bat` 会自动执行此步骤，无需手动运行。

## 打包为 exe

```bash
# 推荐：直接使用 Electron 打包（见下一节）。以下为仅打包后端的命令行参考：
cd taofei_app
set PYTHONPATH=%CD%\build\_noop_site
.venv\Scripts\python.exe -m PyInstaller --noconfirm build\CrewAIWorkbench.spec
```

> **前置**：需先完成 `前端构建` 步骤（或由 build-desktop.bat 自动执行）。spec 会收集项目根 `frontend/` 作为静态资源。

> **注意**：手动打包必须带上 `PYTHONPATH=build\_noop_site`（该目录含一个空 `sitecustomize.py`）。WorkBuddy 会通过环境变量注入删除钩子，导致 PyInstaller 清理缓存时崩溃；空 sitecustomize 让 Python 优先加载它从而绕开。

产物：`dist\CrewAIWorkbench_v<version>\CrewAIWorkbench\CrewAIWorkbench.exe`（含 crewAI + FastAPI + 已构建前端静态资源）

**分发使用：**
1. 将 `dist\CrewAIWorkbench_*\CrewAIWorkbench\` 整个目录复制到目标机器（无需安装 Python）
2. 在目标目录放置 `.env`（含 `DEEPSEEK_API_KEY=sk-xxx`）
3. 双击 `CrewAIWorkbench.exe`，浏览器自动打开工作台

> 打包排除项：`magic`（python-magic）、`lancedb`（向量记忆库）在 Windows 上导入即原生崩溃，且本应用不使用文件类型检测与记忆功能，已在 spec 中排除。

## Electron 桌面客户端（推荐分发方式）

在 PyInstaller 后端之上套一层 **Electron 壳**，变成真正的桌面客户端：原生窗口、无浏览器地址栏、退出自动清理后端进程。

```
desktop/
├── main.js            # Electron 主进程：拉起后端子进程 + 创建窗口 + 生命周期管理
├── preload.js         # 预加载脚本（最小化暴露）
├── launcher.js        # 清理宿主注入后启动 Electron
├── package.json       # electron-builder 配置（NSIS 安装包，extraResources 引用后端与 .env）
└── build-desktop.bat  # 一键打包：前端构建 → PyInstaller 后端 → Electron 安装包
```

**开发模式运行**（带控制台日志）：

```bash
cd desktop
npm install
npm start        # 自动调 .venv 的 Python 启动后端，弹原生窗口
```

**打包为安装程序**（需已安装 Node.js + 项目根存在 `.venv`）：

```bash
# 双击 desktop\build-desktop.bat，或命令行：
cd desktop && build-desktop.bat
# 参数: /b = 只构建前端+后端  /e = 只打包 Electron  /u = 覆盖到 D:\TaofeiAI
# 产物：desktop\release_v4\TaofeiAI Setup 1.2.1.exe
```

脚本内部流程（4 步）：
1. **[0/4]** 在 `frontend-vue/` 执行 `npm install` + `npm run build` → 输出到项目根 `frontend/`
2. **[1/4]** PyInstaller 收集 `backend/` + `frontend/` → `dist/CrewAIWorkbench_v3/CrewAIWorkbench/`
3. **[2/4]** electron-builder 组装 Electron + extraResources（后端 exe 与 `.env`）-> `desktop/release_v4/`
4. **[3/4]** （双击运行或带 `/u`）复制 `win-unpacked` 到 `D:\TaofeiAI` 做免安装覆盖更新

安装包为 **per-user 安装**（装到 `%LocalAppData%\Programs`，无需管理员权限），后端 exe 与 `.env` 打包在 `resources\backend\` 下。`.env` 会一起打包进安装包，安装后开箱即用。

**架构说明**：
1. Electron 启动时 spawn 后端（开发模式用 `.venv\Scripts\python.exe backend\main.py --no-browser`；生产模式用 `process.resourcesPath\backend\CrewAIWorkbench.exe`）
2. 后端 stdout 输出 `__BACKEND_PORT__:{port}`，Electron 解析后轮询 `/api/health` 直到就绪
3. 就绪后 `BrowserWindow` 加载 `http://127.0.0.1:{port}`
4. 窗口关闭/应用退出时 `taskkill /F /IM {exe} /T` 清理后端进程树
5. 单实例锁：重复启动只会聚焦已开窗口

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + Key 状态 |
| POST | `/api/run` | 提交任务 `{"topic": "主题"}` → `{"task_id": "..."}` |
| GET | `/api/status/{task_id}` | 查询任务状态与结果 |
| GET | `/api/tasks` | 最近 20 条任务历史 |
| GET | `/` | 前端工作台页面 |
