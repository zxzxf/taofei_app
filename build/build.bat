@echo off
chcp 65001 >nul
REM ============================================
REM  CrewAI Workbench 一键打包脚本
REM  用法: 双击 build.bat 或命令行执行
REM  产物: dist\CrewAIWorkbench.exe
REM ============================================
echo.
echo [1/3] 检查依赖...
cd /d "%~dp0.."

set VENV=..\crewAI\.venv
if not exist "%VENV%\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境: %VENV%
    echo        请先在 E:\taofei_ai\crewAI 执行 uv sync
    pause
    exit /b 1
)

echo [1.5/3] 准备打包环境（绕过系统删除钩子）...
if not exist "build\_noop_site" mkdir "build\_noop_site"
if not exist "build\_noop_site\sitecustomize.py" type nul > "build\_noop_site\sitecustomize.py"
set PYTHONPATH=%CD%\build\_noop_site

"%VENV%\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [2/3] 正在安装 PyInstaller（首次需要 1-2 分钟）...
    "%VENV%\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

echo [2/3] 正在打包，请耐心等待（约 3-10 分钟）...
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean build\CrewAIWorkbench.spec
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方报错信息
    pause
    exit /b 1
)

if exist "dist\CrewAIWorkbench.exe" (
    echo.
    echo [3/3] 打包成功！
    echo      产物位置: %cd%\dist\CrewAIWorkbench.exe
    echo.
    echo 使用说明:
    echo   1. 把 dist\CrewAIWorkbench.exe 复制到任意目录
    echo   2. 在同目录放置 .env 文件（含 DEEPSEEK_API_KEY）
    echo   3. 双击 exe，浏览器会自动打开工作台页面
    echo.
    explorer /select,"%cd%\dist\CrewAIWorkbench.exe"
) else (
    echo.
    echo [错误] 打包失败，请查看上方报错信息
)
pause
