@echo off
chcp 65001 >nul
REM ============================================
REM  CrewAI Workbench Build Script
REM  Usage: double-click build.bat
REM  Output: dist\CrewAIWorkbench\ (directory mode)
REM ============================================
echo.
echo [1/3] Checking environment...
cd /d "%~dp0.."

set VENV=.venv
if not exist "%VENV%\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found: %VENV%
    echo         Please run: python -m venv .venv and install dependencies first
    pause
    exit /b 1
)

echo [1.5/3] Preparing noop sitecustomize...
if not exist "build\_noop_site" mkdir "build\_noop_site"
if not exist "build\_noop_site\sitecustomize.py" type nul > "build\_noop_site\sitecustomize.py"
set PYTHONPATH=%CD%\build\_noop_site

"%VENV%\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [2/3] Installing PyInstaller...
    "%VENV%\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed
        pause
        exit /b 1
    )
)

echo [2/3] Building (please wait 3-10 minutes)...
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean build\CrewAIWorkbench.spec
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed, check error messages above
    pause
    exit /b 1
)

if exist "dist\CrewAIWorkbench\CrewAIWorkbench.exe" (
    echo.
    echo [3/3] Build success!
    echo      Output: %cd%\dist\CrewAIWorkbench\
    echo.
    echo Usage:
    echo   1. Copy dist\CrewAIWorkbench folder to target location
    echo   2. Place .env file (with DEEPSEEK_API_KEY) in the same folder
    echo   3. Double-click CrewAIWorkbench.exe to start
    echo.
    explorer /select,"%cd%\dist\CrewAIWorkbench\CrewAIWorkbench.exe"
) else (
    echo.
    echo [ERROR] Build failed, check error messages above
)
pause
