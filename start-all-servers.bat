@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0" || exit /b 1

set "API_PORT=8018"
set "DASH_PORT=3018"

echo ============================================
echo   Shorts Factory AI - Start All Servers
echo ============================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv tidak ditemukan di PATH.
    echo Install: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm tidak ditemukan di PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv tidak ada. Jalankan: uv sync --frozen
    pause
    exit /b 1
)

if not exist "apps\dashboard\node_modules\.bin\next.cmd" (
    echo [ERROR] Dashboard dependencies belum terinstall.
    echo Jalankan: cd apps\dashboard ^&^& npm ci --include=dev
    pause
    exit /b 1
)

echo [1/3] Membersihkan proses lama di port %API_PORT% dan %DASH_PORT%...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%API_PORT% " ^| findstr LISTENING') do (
    taskkill /f /pid %%p >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%DASH_PORT% " ^| findstr LISTENING') do (
    taskkill /f /pid %%p >nul 2>&1
)

echo [2/3] Menjalankan API server (port %API_PORT%)...
start "Shorts Factory API" /D "%CD%" cmd /d /k "uv run python scripts\run_studio_api.py"

echo [3/3] Menjalankan Dashboard (port %DASH_PORT%)...
start "Shorts Factory Studio" /D "%CD%\apps\dashboard" cmd /d /k "npm run dev"

echo.
echo ============================================
echo   Server berjalan:
echo   API      : http://127.0.0.1:%API_PORT%
echo   Dashboard: http://127.0.0.1:%DASH_PORT%
echo ============================================
echo.
echo Tekan tombol apa saja untuk membuka dashboard di browser...
pause >nul
start "" "http://127.0.0.1:%DASH_PORT%"

endlocal
exit /b 0
