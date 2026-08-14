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

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + Key 状态 |
| POST | `/api/run` | 提交任务 `{"topic": "主题"}` → `{"task_id": "..."}` |
| GET | `/api/status/{task_id}` | 查询任务状态与结果 |
| GET | `/api/tasks` | 最近 20 条任务历史 |
| GET | `/` | 前端工作台页面 |
