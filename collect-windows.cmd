@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv-collector
) else (
    python -m venv .venv-collector
)
if errorlevel 1 goto python_error
".venv-collector\Scripts\python.exe" -m pip install -r requirements-collector.txt
if errorlevel 1 goto install_error
".venv-collector\Scripts\python.exe" tools\collect_pc.py
pause
exit /b
:python_error
echo Python 3.10 or newer is required. Install Python from https://www.python.org/downloads/windows/
pause
exit /b 1
:install_error
echo Dependency installation failed. Check your internet connection and try again.
pause
exit /b 1
