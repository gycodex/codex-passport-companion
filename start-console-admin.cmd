@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_console.ps1" -Administrator
if errorlevel 1 pause
