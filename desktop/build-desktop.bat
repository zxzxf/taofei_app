@echo off
chcp 65001 >nul
REM ============================================
REM  TaofeiAI Desktop Build Script
REM
REM  Usage:
REM    Double-click            = Full build (frontend + backend + installer + upgrade)
REM    build-desktop.bat /b    = Backend only (frontend + PyInstaller)
REM    build-desktop.bat /e    = Electron installer only
REM    build-desktop.bat /u    = Update D:\TaofeiAI only
REM
REM  Output:
REM    dist\TaofeiAPI\TaofeiAPI.exe              = PyInstaller backend (onedir dir, includes frontend)
REM    desktop\release_v4\TaofeiAI Setup 1.2.1.exe = NSIS installer (final release)
REM    desktop\release_v4\win-unpacked\            = Portable version
REM
REM  Prerequisites: .venv created + Node.js installed
REM  Steps:
REM    [0/4] frontend-vue npm install + npm run build -> output to project root\frontend\
REM    [1/4] PyInstaller collects frontend\ + backend\ -> dist\TaofeiAPI\ (onedir, no self-extract on launch)
REM    [2/4] electron-builder combines Electron + extraResources -> release_v4\
REM    [3/4] (optional) copy win-unpacked to D:\TaofeiAI
REM ============================================
setlocal enabledelayedexpansion

REM ---------- Parse args ----------
set "MODE=full"
if /i "%~1"=="/b" set "MODE=backend"
if /i "%~1"=="/e" set "MODE=electron"
if /i "%~1"=="/u" set "MODE=upgrade"

REM ---------- Mirrors ----------
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"
set "ELECTRON_RUN_AS_NODE="
set "CI=false"

REM ---------- Paths ----------
set "RELEASE_VER=release_v4"
set "INSTALL_DIR=D:\TaofeiAI"

cd /d "%~dp0.."
set "PROJECT_ROOT=%cd%"
set "DESKTOP_DIR=%PROJECT_ROOT%\desktop"
set "DIST_DIR=%PROJECT_ROOT%\dist"
set "BACKEND_EXE=%DIST_DIR%\TaofeiAPI\TaofeiAPI.exe"

echo.
echo ========================================
echo  TaofeiAI Desktop Build
echo  Mode: %MODE%
echo ========================================
echo.

REM ==========================================
REM  Step 0: Build frontend (Vite output to project root\frontend\)
REM  Step 1: PyInstaller backend (collects frontend\)
REM ==========================================
if /i "%MODE%"=="electron" goto step_electron
if /i "%MODE%"=="upgrade" goto step_upgrade

echo [0/3] Building frontend with Vite...
cd /d "%PROJECT_ROOT%\frontend-vue"

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js from https://nodejs.org
    pause
    exit /b 1
)

if not exist "node_modules\vite\bin\vite.js" (
    echo        npm install...
    call npm install
    if errorlevel 1 ( echo [ERROR] npm install failed & pause & exit /b 1 )
) else (
    echo        node_modules OK, skipping install
)

echo        npm run build...
call npm run build
if errorlevel 1 ( echo [ERROR] Frontend build failed & pause & exit /b 1 )

if not exist "%PROJECT_ROOT%\frontend\index.html" (
    echo [ERROR] Frontend build did not produce frontend\index.html
    pause
    exit /b 1
)
echo       [OK] Frontend: %PROJECT_ROOT%\frontend\

echo.
echo [1/3] Building backend with PyInstaller...

cd /d "%PROJECT_ROOT%"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found
    echo         Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt pyinstaller
    pause
    exit /b 1
)

REM ---------- Dependency check ----------
echo        Checking required Python packages...
".venv\Scripts\python.exe" -c "import taofei_api_core, taofei_api_files, taofei_api_tools, taofei_api_cli, taofei_api, sentence_transformers, PyPDF2, numpy" >nul 2>&1
if errorlevel 1 (
    echo        Required packages missing, installing from requirements.txt...
    if not exist "requirements.txt" (
        echo [ERROR] requirements.txt not found in %PROJECT_ROOT%
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 ( echo [ERROR] Dependency installation failed & pause & exit /b 1 )

    echo        Re-checking required packages...
    ".venv\Scripts\python.exe" -c "import taofei_api_core, taofei_api_files, taofei_api_tools, taofei_api_cli, taofei_api, sentence_transformers, PyPDF2, numpy" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Required packages still missing after installation
        pause
        exit /b 1
    )
)
echo       [OK] Python dependencies OK

if not exist "build\_noop_site" mkdir "build\_noop_site"
if not exist "build\_noop_site\sitecustomize.py" type nul > "build\_noop_site\sitecustomize.py"
set "PYTHONPATH=%PROJECT_ROOT%\build\_noop_site"

".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo        Installing PyInstaller...
    ".venv\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 ( echo [ERROR] PyInstaller install failed & pause & exit /b 1 )
)

echo        PyInstaller building (onedir, no self-extract)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ^
    --distpath "dist" ^
    --workpath "build\pyinstaller" ^
    build\TaofeiAPI.spec
if errorlevel 1 ( echo [ERROR] Backend build failed & pause & exit /b 1 )

if not exist "%BACKEND_EXE%" (
    echo [ERROR] Backend exe not found: %BACKEND_EXE%
    pause
    exit /b 1
)
echo       [OK] Backend: %BACKEND_EXE%

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

if not exist "node_modules\electron\package.json" (
    echo        npm install...
    call npm install
    if errorlevel 1 ( echo [ERROR] npm install failed & pause & exit /b 1 )
) else (
    echo        node_modules OK, skipping install
)

REM Guard 1: kill running desktop app so files are not locked during build
taskkill /F /IM TaofeiAI.exe /T >nul 2>&1
taskkill /F /IM TaofeiAPI.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul 2>&1

REM Guard 2: remove old win-unpacked BEFORE building.
REM If electron-builder fails, stale artifacts from a previous build can never
REM be mistaken for fresh output and deployed to %INSTALL_DIR%
if exist "%RELEASE_VER%\win-unpacked" (
    echo        Cleaning old win-unpacked to avoid stale artifacts...
    rd /s /q "%RELEASE_VER%\win-unpacked"
    if exist "%RELEASE_VER%\win-unpacked" (
        echo [ERROR] Cannot remove old win-unpacked - a file is locked by another process.
        echo        Common cause: app.asar or exe opened inside the IDE - close that tab,
        echo        or an antivirus is scanning - wait a moment, then rebuild.
        echo        You can also switch the output dir in desktop\package.json
        echo        ^(directories.output^) to a fresh name to bypass the locked file.
        pause
        exit /b 1
    )
)

echo        electron-builder...
call npm run dist
if errorlevel 1 (
    echo [ERROR] electron-builder failed. Old artifacts already cleaned,
    echo        script will NOT continue with stale files. Fix the error above and rebuild.
    pause
    exit /b 1
)

if not exist "%RELEASE_VER%\win-unpacked\TaofeiAI.exe" (
    echo [ERROR] Desktop build failed: no win-unpacked
    pause
    exit /b 1
)

REM Guard 3: extraResources MUST contain the freshly built backend exe,
REM otherwise the deployed desktop app would silently run OLD code
if not exist "%RELEASE_VER%\win-unpacked\resources\backend\TaofeiAPI\TaofeiAPI.exe" (
    echo [ERROR] VERIFICATION FAILED:
    echo        %RELEASE_VER%\win-unpacked\resources\backend\TaofeiAPI\TaofeiAPI.exe not found
    echo        extraResources did not include the backend exe.
    echo        Do NOT deploy this build - fix electron-builder config and rebuild.
    pause
    exit /b 1
)
echo       [OK] Desktop: %DESKTOP_DIR%\%RELEASE_VER%\

if /i "%MODE%"=="electron" goto done

REM ==========================================
REM  Step 3: Update D:\TaofeiAI
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

REM Guard 4: source build must contain backend exe before deploying
if not exist "%RELEASE_VER%\win-unpacked\resources\backend\TaofeiAPI\TaofeiAPI.exe" (
    echo [ERROR] %RELEASE_VER%\win-unpacked\resources\backend\TaofeiAPI\TaofeiAPI.exe not found
    echo        Build is incomplete - run full build first, never deploy without backend exe
    pause
    exit /b 1
)

taskkill /F /IM TaofeiAI.exe /T >nul 2>&1
taskkill /F /IM TaofeiAPI.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1

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

REM Guard 5: verify backend exe exists in target dir after copy
if not exist "%INSTALL_DIR%\resources\backend\TaofeiAPI\TaofeiAPI.exe" (
    echo [ERROR] Verify failed: %INSTALL_DIR%\resources\backend\TaofeiAPI\TaofeiAPI.exe missing
    pause
    exit /b 1
)
echo       [OK] Updated: %INSTALL_DIR%
echo       Verify: launch TaofeiAI.exe, then open http://127.0.0.1:8000/api/version
echo              and confirm the commit/build time matches this build.

:done
echo.
echo ========================================
echo  Packaging completed successfully!
echo ========================================
echo.
echo  Backend:   %PROJECT_ROOT%\dist\TaofeiAPI\TaofeiAPI.exe
echo  Installer: %DESKTOP_DIR%\%RELEASE_VER%\TaofeiAI Setup 1.2.1.exe
echo  Portable:  %DESKTOP_DIR%\%RELEASE_VER%\win-unpacked\
echo  Installed: %INSTALL_DIR%
echo.
explorer "%DESKTOP_DIR%\%RELEASE_VER%"
pause
