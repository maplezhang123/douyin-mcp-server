@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo Douyin MCP Server - Windows Launcher
echo ========================================

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv not found.
    echo Install uv first: https://docs.astral.sh/uv/
    pause
    exit /b 1
)
echo [OK] uv

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found.
    pause
    exit /b 1
)
echo [OK] Node.js

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found.
    pause
    exit /b 1
)
echo [OK] npm

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ffmpeg not found.
    pause
    exit /b 1
)
echo [OK] ffmpeg

if not exist "node_modules\playwright\package.json" (
    echo [INFO] Installing Node dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)
echo [OK] Playwright package

echo [INFO] Syncing Python dependencies...
call uv sync --extra web
if errorlevel 1 (
    echo [ERROR] uv sync failed.
    pause
    exit /b 1
)

echo.
echo [START] WebUI
echo [URL] http://localhost:8080
echo.

call uv run --extra web python web/app.py

if errorlevel 1 (
    echo.
    echo [ERROR] WebUI exited with an error.
    pause
)

endlocal
