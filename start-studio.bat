@echo off
setlocal
cd /d "%~dp0" || exit /b 1
where uv >nul 2>&1
if errorlevel 1 (echo uv is not on PATH. & exit /b 1)
where npm >nul 2>&1
if errorlevel 1 (echo npm is not on PATH. & exit /b 1)
if not exist ".venv\Scripts\python.exe" (echo Run uv sync --frozen first. & exit /b 1)
if not exist "apps\dashboard\node_modules\.bin\next.cmd" (echo Install dashboard dependencies with npm ci --include=dev. & exit /b 1)
if /i "%~1"=="--check" (echo Studio prerequisites OK. & exit /b 0)
if not "%~1"=="" (echo Usage: start-studio.bat [--check] & exit /b 2)
start "Shorts Factory API" /D "%CD%" cmd /d /k "uv run uvicorn apps.api.server:app --host 127.0.0.1 --port 8018"
if errorlevel 1 (echo API window could not be opened. & exit /b 1)
start "Shorts Factory Studio" /D "%CD%\apps\dashboard" cmd /d /k "npm run dev"
if errorlevel 1 (echo Studio window could not be opened. & exit /b 1)
echo API window opened. Studio window opened.
echo After both servers are ready, visit http://127.0.0.1:3018
exit /b 0
