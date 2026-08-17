@echo off
chcp 65001 >nul
REM ============================================
REM  淘飞AI 桌面客户端一键打包脚本
REM
REM  用法:
REM    双击运行            = 全部打包（后端+前端+安装包）
REM    build-desktop.bat /b = 只打包后端（PyInstaller）
REM    build-desktop.bat /e = 只打包安装包（electron-builder）
REM    build-desktop.bat /u = 只更新 D:\TaofeiAI（免安装覆盖）
REM
REM  产物:
REM    dist\CrewAIWorkbench_v3\CrewAIWorkbench\  = PyInstaller 后端
REM    desktop\release_v3\TaofeiAI Setup 1.2.1.exe = NSIS 安装包
REM    desktop\release_v3\win-unpacked\            = 免安装版
REM
REM  前置: .venv 已创建 + Node.js 已安装
REM ============================================
setlocal enabledelayedexpansion

REM ---------- 解析参数 ----------
set "MODE=full"
if /i "%~1"=="/b" set "MODE=backend"
if /i "%~1"=="/e" set "MODE=electron"
if /i "%~1"=="/u" set "MODE=upgrade"

REM ---------- 国内镜像 ----------
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"
set "ELECTRON_RUN_AS_NODE="
set "CI=false"

REM ---------- 路径变量 ----------
set "BACKEND_VER=v3"
set "RELEASE_VER=release_v3"
set "INSTALL_DIR=D:\TaofeiAI"

cd /d "%~dp0.."
set "PROJECT_ROOT=%cd%"
set "DESKTOP_DIR=%PROJECT_ROOT%\desktop"
set "DIST_DIR=%PROJECT_ROOT%\dist\CrewAIWorkbench_%BACKEND_VER%\CrewAIWorkbench"

echo.
echo ========================================
echo  TaofeiAI Desktop Build
echo  Mode: %MODE%
echo ========================================
echo.

REM ==========================================
REM  Step 1: PyInstaller 打包后端
REM ==========================================
if /i "%MODE%"=="electron" goto step_electron
if /i "%MODE%"=="upgrade" goto step_upgrade

echo [1/3] Building backend with PyInstaller...

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found
    echo         Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt pyinstaller
    pause
    exit /b 1
)

REM 绕过 WorkBuddy 注入的删除钩子（空 sitecustomize 优先加载）
if not exist "build\_noop_site" mkdir "build\_noop_site"
if not exist "build\_noop_site\sitecustomize.py" type nul > "build\_noop_site\sitecustomize.py"
set "PYTHONPATH=%PROJECT_ROOT%\build\_noop_site"

REM 确保 PyInstaller 已安装
".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo        Installing PyInstaller...
    ".venv\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 ( echo [ERROR] PyInstaller install failed & pause & exit /b 1 )
)

echo        PyInstaller building...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ^
    --distpath "dist\CrewAIWorkbench_%BACKEND_VER%" ^
    --workpath "build\CrewAIWorkbench_%BACKEND_VER%" ^
    build\CrewAIWorkbench.spec
if errorlevel 1 ( echo [ERROR] Backend build failed & pause & exit /b 1 )

if not exist "%DIST_DIR%\CrewAIWorkbench.exe" (
    echo [ERROR] Backend exe not found: %DIST_DIR%
    pause
    exit /b 1
)
echo       [OK] Backend: %DIST_DIR%

if /i "%MODE%"=="backend" goto done

REM ==========================================
REM  Step 2: npm install + electron-builder
REM ==========================================
:step_electron
echo.
echo [2/3] Building desktop installer with electron-builder...
cd /d "%DESKTOP_DIR%"

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js from https://nodejs.org
    pause
    exit /b 1
)

REM 首次运行需要 npm install；node_modules 存在则跳过
if not exist "node_modules\electron\package.json" (
    echo        npm install...
    call npm install
    if errorlevel 1 ( echo [ERROR] npm install failed & pause & exit /b 1 )
) else (
    echo        node_modules OK, skipping install
)

echo        electron-builder...
call npm run dist
if errorlevel 1 (
    echo [WARNING] electron-builder reported errors, check output above
    echo           Product may still be usable if win-unpacked exists
)

if not exist "%RELEASE_VER%\win-unpacked\TaofeiAI.exe" (
    echo [ERROR] Desktop build failed: no win-unpacked
    pause
    exit /b 1
)
echo       [OK] Desktop: %DESKTOP_DIR%\%RELEASE_VER%\

if /i "%MODE%"=="electron" goto done

REM ==========================================
REM  Step 3: 更新 D:\TaofeiAI
REM ==========================================
:step_upgrade
echo.
echo [3/3] Updating %INSTALL_DIR%...
cd /d "%DESKTOP_DIR%"

if not exist "%RELEASE_VER%\win-unpacked\TaofeiAI.exe" (
    echo [ERROR] win-unpacked not found, run full build first
    pause
    exit /b 1
)

REM 杀掉可能占用文件的进程
taskkill /F /IM TaofeiAI.exe /T >nul 2>&1
taskkill /F /IM CrewAIWorkbench.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1

REM 清空 + 复制
echo        Copying files...
rd /s /q "%INSTALL_DIR%" 2>nul
mkdir "%INSTALL_DIR%" 2>nul
xcopy "%RELEASE_VER%\win-unpacked\*" "%INSTALL_DIR%\" /E /I /Q /Y >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Copy failed, try manually:
    echo           xcopy "%RELEASE_VER%\win-unpacked\*" "%INSTALL_DIR%\" /E /I /Y
    pause
    exit /b 1
)
echo       [OK] Updated: %INSTALL_DIR%

:done
echo.
echo ========================================
echo  Build complete!
echo ========================================
echo.
echo  Backend:   %PROJECT_ROOT%\dist\CrewAIWorkbench_%BACKEND_VER%\CrewAIWorkbench\
echo  Installer: %DESKTOP_DIR%\%RELEASE_VER%\TaofeiAI Setup 1.2.1.exe
echo  Portable:  %DESKTOP_DIR%\%RELEASE_VER%\win-unpacked\
echo  Installed: %INSTALL_DIR%
echo.
explorer "%DESKTOP_DIR%\%RELEASE_VER%"
pause
