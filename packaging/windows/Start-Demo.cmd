@echo off
"%~dp0ControlLabCLI.exe" run --controller reference --render --episodes 3
if errorlevel 1 pause
