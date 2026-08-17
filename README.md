# CrewAI Workbench — AI 智能体工作台

基于 **CrewAI + FastAPI + Web 前端** 的最小可运行桌面应用项目，支持打包为单个 exe。

## 功能

- 💬 输入任意主题，自动创建「研究员 + 分析师」双 Agent 顺序协作任务
- 📊 左侧导航 + 模板卡片 + 任务历史，仿 IDE 工作台界面
- 📄 结果实时展示（Markdown 渲染，可一键复制）
- 📦 支持 PyInstaller 打包为独立 exe

## 项目结构

```
crewai_app/
├── backend/
│   └── main.py          # FastAPI 后端：crewAI 封装 + 任务 API + 静态页面
├── frontend/
│   └── index.html       # 前端工作台页面（纯 HTML/CSS/JS，无构建依赖）
├── build/
│   ├── CrewAIWorkbench.spec   # PyInstaller 打包配置
│   └── build.bat              # 一键打包脚本
├── requirements.txt
└── .env.example         # 配置模板（复制为 .env 并填入 API Key）
```

## 快速开始（开发模式）

```bash
# 1. 准备环境（复用 crewAI 仓库的虚拟环境）
cd E:\taofei_ai\crewAI && uv sync

# 2. 配置 API Key
cd E:\taofei_ai\crewai_app
copy .env.example .env   # 编辑 .env，填入 DEEPSEEK_API_KEY

# 3. 启动服务（自动打开浏览器）
..\crewAI\.venv\Scripts\python.exe backend\main.py
```

访问 http://127.0.0.1:8000 即可使用。

## 打包为 exe

```bash
# 推荐：双击运行 build\build.bat（已内置环境准备与钩子绕过逻辑）
# 或命令行手动打包：
cd E:\taofei_ai\crewai_app
set PYTHONPATH=%CD%\build\_noop_site
..\crewAI\.venv\Scripts\python.exe -m PyInstaller --noconfirm build\CrewAIWorkbench.spec
```

> **注意**：手动打包必须带上 `PYTHONPATH=build\_noop_site`（该目录含一个空 `sitecustomize.py`）。WorkBuddy 会通过环境变量注入删除钩子，导致 PyInstaller 清理缓存时崩溃；空 sitecustomize 让 Python 优先加载它从而绕开。

产物：`dist\CrewAIWorkbench.exe`（**已实测通过**，约 113MB，含 crewAI + FastAPI + DeepSeek SDK）

**分发使用：**
1. 将 `CrewAIWorkbench.exe` 复制到目标机器（无需安装 Python）
2. 同目录放置 `.env`（含 `DEEPSEEK_API_KEY=sk-xxx`）
3. 双击 exe，浏览器自动打开工作台

> 打包排除项：`magic`（python-magic）、`lancedb`（向量记忆库）在 Windows 上导入即原生崩溃，且本应用不使用文件类型检测与记忆功能，已在 spec 中排除。

## Electron 桌面客户端（推荐分发方式）

在 PyInstaller 后端之上套一层 **Electron 壳**，变成真正的桌面客户端：原生窗口、无浏览器地址栏、退出自动清理后端进程。

```
desktop/
├── main.js            # Electron 主进程：拉起后端子进程 + 创建窗口 + 生命周期管理
├── preload.js         # 预加载脚本（最小化暴露）
├── package.json       # electron-builder 配置
└── build-desktop.bat  # 一键打包：PyInstaller 后端 → Electron 安装包
```

**开发模式运行**（带控制台日志）：

```bash
cd desktop
npm install
npm start        # 自动调 .venv 的 Python 启动后端，弹原生窗口
```

**打包为安装程序**（需已安装 Node.js）：

```bash
# 双击 desktop\build-desktop.bat，或命令行：
cd desktop && build-desktop.bat
# 产物：desktop\release\TaofeiAI Setup 1.2.0.exe
```

安装包为 **per-user 安装**（装到 %LocalAppData%\Programs，无需管理员权限），后端 exe 与 `.env` 打包在 `resources\backend\` 下。

**架构说明**：
1. Electron 启动时 spawn 后端（开发模式用 `.venv\Scripts\python.exe backend\main.py --no-browser`；生产模式用打包内嵌的 `CrewAIWorkbench.exe`）
2. 后端 stdout 输出 `__BACKEND_PORT__:{port}`，Electron 解析后轮询 `/api/health` 直到就绪
3. 就绪后 `BrowserWindow` 加载 `http://127.0.0.1:{port}`
4. 窗口关闭/应用退出时 `taskkill /t` 清理后端进程树
5. 单实例锁：重复启动只会聚焦已开窗口

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + Key 状态 |
| POST | `/api/run` | 提交任务 `{"topic": "主题"}` → `{"task_id": "..."}` |
| GET | `/api/status/{task_id}` | 查询任务状态与结果 |
| GET | `/api/tasks` | 最近 20 条任务历史 |
| GET | `/` | 前端工作台页面 |
