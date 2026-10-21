@echo off
setlocal
cd /d "%~dp0" || exit /b 1
where uv >nul 2>&1
if errorlevel 1 (echo uv is not on PATH. & exit /b 1)
where node >nul 2>&1
if errorlevel 1 (echo Node.js is not on PATH. & exit /b 1)
where ffmpeg >nul 2>&1
if errorlevel 1 (echo FFmpeg is not on PATH. & exit /b 1)
where ffprobe >nul 2>&1
if errorlevel 1 (echo FFprobe is not on PATH. & exit /b 1)
if not exist ".venv\Scripts\python.exe" (echo Run uv sync --frozen first. & exit /b 1)
if not exist "packages\video\node_modules\.bin\remotion.cmd" (echo Install video dependencies with npm ci --include=dev. & exit /b 1)
if /i "%~1"=="--check" (echo Demo prerequisites OK. & exit /b 0)
if /i "%~1"=="--resume" goto resume
if not "%~1"=="" (echo Usage: run-demo.bat [--check ^| --resume JOB_ID] & exit /b 2)
uv run python scripts\run_pipeline.py --title "Demo cahaya dari masa lalu" --stop approval
goto finished
:resume
if "%~2"=="" (echo Usage: run-demo.bat --resume JOB_ID & exit /b 2)
uv run python scripts\run_pipeline.py --resume "%~2" --stop approval
:finished
set "STATUS=%ERRORLEVEL%"
echo.
echo Pipeline exit code: %STATUS%
echo Render output is under data\jobs\JOB_ID\output.mp4
pause
exit /b %STATUS%
