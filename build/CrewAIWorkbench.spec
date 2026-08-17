# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：CrewAI Workbench"""
import os

from PyInstaller.utils.hooks import collect_data_files

# 打包后的可执行文件名
NAME = "CrewAIWorkbench"

# 项目根目录：spec 中的相对路径以 spec 所在目录(build/)为基准，
# 因此必须基于 SPECPATH 显式计算，否则会去找 build/build/backend/main.py
PROJECT_ROOT = os.path.dirname(SPECPATH)  # E:\taofei_ai\crewai_app

# 前端静态文件目录（打包后嵌入到 _MEIPASS/frontend）
frontend_dir = os.path.join(PROJECT_ROOT, "frontend")

# crewai 需要 translations/*.json 等数据文件（i18n 提示词），
# PyInstaller 默认只收集 .py，必须用 collect_data_files 显式带上
crewai_datas = collect_data_files("crewai")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "backend", "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=crewai_datas + [(frontend_dir, "frontend")],
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
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 控制台窗口（显示启动日志）；如需无窗口改为 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=NAME,
)
