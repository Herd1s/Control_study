@echo off
if not exist "%~dp0Builds\Windows\ControlLab Unity.exe" (
    echo No Windows build yet. Activate Unity, then run Build-Windows.cmd first.
    pause
    exit /b 1
)
start "ControlLab Unity" /D "%~dp0Builds\Windows" "%~dp0Builds\Windows\ControlLab Unity.exe"
