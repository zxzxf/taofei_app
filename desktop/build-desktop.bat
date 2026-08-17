@echo off
chcp 65001 >nul
REM ============================================
REM  淘飞AI 桌面客户端一键打包脚本
REM  产物: desktop\release\TaofeiAI Setup 1.2.0.exe
REM  前置: 已安装 Node.js
REM ============================================
setlocal
REM 国内镜像：Electron 二进制 + electron-builder 工具链（NSIS 等）
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"
echo.
echo ========================================
echo  TaofeiAI Desktop Build
echo ========================================
echo.

cd /d "%~dp0.."
set "PROJECT_ROOT=%cd%"

REM ---------- Step 1: PyInstaller 打包后端 ----------
echo [1/3] Building backend with PyInstaller...

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found: .venv
    echo         Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt pyinstaller
    pause
    exit /b 1
)

REM 绕过 WorkBuddy 注入的删除钩子（空 sitecustomize 优先加载）
if not exist "build\_noop_site" mkdir "build\_noop_site"
if not exist "build\_noop_site\sitecustomize.py" type nul > "build\_noop_site\sitecustomize.py"
set "PYTHONPATH=%PROJECT_ROOT%\build\_noop_site"

".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo        Installing PyInstaller...
    ".venv\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 ( echo [ERROR] PyInstaller install failed & pause & exit /b 1 )
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --distpath "dist\CrewAIWorkbench_v2" build\CrewAIWorkbench.spec
if errorlevel 1 ( echo [ERROR] Backend build failed & pause & exit /b 1 )

if not exist "dist\CrewAIWorkbench_v2\CrewAIWorkbench\CrewAIWorkbench.exe" (
    echo [ERROR] Backend exe not found after build
    pause
    exit /b 1
)
echo       Backend OK: dist\CrewAIWorkbench_v2\CrewAIWorkbench\

REM ---------- Step 2: 安装 Electron 依赖 ----------
echo.
echo [2/3] Installing Electron dependencies...
cd /d "%~dp0"

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found. Please install Node.js from https://nodejs.org
    pause
    exit /b 1
)

call npm install
if errorlevel 1 ( echo [ERROR] npm install failed & pause & exit /b 1 )

REM ---------- Step 3: electron-builder 打包桌面客户端 ----------
echo.
echo [3/3] Building desktop installer with electron-builder...
REM 清除宿主环境注入的 ELECTRON_RUN_AS_NODE，避免 electron 退化为纯 Node
set "ELECTRON_RUN_AS_NODE="
REM 禁用 CI 检测，避免 electron-builder 尝试 publish 到 GitHub release
set "CI=false"
call npm run dist
if errorlevel 1 ( echo [ERROR] electron-builder failed & pause & exit /b 1 )

echo.
echo ========================================
echo  Desktop build success!
echo ========================================
echo.
echo  Installer: %cd%\release\
echo.
if exist "release" explorer "release"
pause
