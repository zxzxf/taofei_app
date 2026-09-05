# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：TaofeiAPI 后端"""
import datetime
import os
import subprocess

from PyInstaller.utils.hooks import collect_data_files

# 打包后的可执行文件名
NAME = "TaofeiAPI"

# 项目根目录：spec 中的相对路径以 spec 所在目录(build/)为基准，
# 因此必须基于 SPECPATH 显式计算，否则会去找 build/build/backend/main.py
PROJECT_ROOT = os.path.dirname(SPECPATH)


# ---------------------------------------------------------------
# 构建时生成版本文件 backend/_version.py（git commit + 构建时间）。
# 运行时由 main.py 读取，通过 /api/version 与启动日志展示，
# 用于快速确认打包产物里到底是哪次提交的代码（防止旧代码被当成新版本部署）。
# ---------------------------------------------------------------
def _gen_version_file():
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        ).stdout.strip() or "unknown"
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        ).stdout.strip())
    except Exception:
        commit, dirty = "unknown", False
    content = (
        "# 由 PyInstaller 打包时自动生成，请勿手动编辑或提交\n"
        f"BUILD_COMMIT = {commit!r}\n"
        f"BUILD_TIME = {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')!r}\n"
        f"BUILD_DIRTY = {dirty!r}\n"
    )
    with open(os.path.join(PROJECT_ROOT, "backend", "_version.py"), "w", encoding="utf-8") as f:
        f.write(content)


_gen_version_file()

# 前端静态文件目录（打包后嵌入到 _MEIPASS/frontend）
frontend_dir = os.path.join(PROJECT_ROOT, "frontend")

# taofei_api 需要 translations/*.json 等数据文件（i18n 提示词），
# PyInstaller 默认只收集 .py，必须用 collect_data_files 显式带上
taofei_api_datas = collect_data_files("taofei_api")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "backend", "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=taofei_api_datas + [
        (frontend_dir, "frontend"),
        # browse_directory.ps1 打包到 _MEIPASS/backend/，与 main.py 同级（BASE_DIR/backend/）
        (os.path.join(PROJECT_ROOT, "backend", "browse_directory.ps1"), "backend"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "wf_engine",
        "wf_engine.engine",
        "wf_engine.dsl",
        "wf_engine.nodes",
        "wf_engine.variable_pool",
        "langchain_community",
        "langchain_community.chat_models",
        "sentence_transformers",
        "numpy",
        "PyPDF2",
        # ---- Hermes 风格重构新增包（函数内延迟导入，PyInstaller 静态分析扫不到）----
        # session：会话管理 + 上下文压缩（main.py 内多处 from session.xxx import）
        "session",
        "session.manager",
        "session.session",
        "session.context_compressor",
        # providers：多提供商 + 故障转移（阶段 6）
        "providers",
        "providers.base",
        "providers.openai_compat",
        "providers.anthropic",
        "providers.fallback_chain",
        "providers.fallback_llm",
        "providers.registry",
        # agent/delegator：子代理并行执行器（agent_tools.py 内 from agent.delegator import）
        "agent",
        "agent.delegator",
        # agent/error_classifier：阶段 6.4 错误分类器（main.py / fallback_chain 函数内导入）
        "agent.error_classifier",
        # tools：联网工具 + 注册中心（agent_tools.py 内 from tools.xxx import）
        "tools",
        "tools.registry",
        "tools.web_search",
        "tools.web_extract",
        # skills_lifecycle：技能创建/沉淀（main.py + agent_tools.py 内延迟导入）
        "skills_lifecycle",
        # cron：定时任务调度器（main.py 函数内 from cron.scheduler import）
        "cron",
        "cron.scheduler",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # magic(python-magic)与 lancedb(向量记忆库)在 Windows 上导入即原生崩溃，
    # 本应用仅使用 Agent 对话流程，不使用文件类型检测与记忆功能，直接排除
    excludes=[
        "magic",
        "lancedb",
        "lance_namespace",
        "lance_namespace_urllib3_client",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 控制台窗口（显示启动日志）；如需无窗口改为 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
