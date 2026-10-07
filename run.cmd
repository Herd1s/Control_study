@echo off
setlocal
set PYTHONUTF8=1
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Please run setup.ps1 to create this project's Python environment.
    exit /b 1
)
if "%~1"=="" (
    "%~dp0.venv\Scripts\python.exe" -m control_lab
) else (
    "%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
)
exit /b %ERRORLEVEL%
