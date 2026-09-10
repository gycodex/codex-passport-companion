@echo off
cd /d "%~dp0"
if not exist ".venv-console\Scripts\python.exe" (
  py -3 -m venv .venv-console
  if errorlevel 1 goto error
)
.venv-console\Scripts\python.exe -c "import bleak, cryptography" >nul 2>&1
if errorlevel 1 (
  .venv-console\Scripts\python.exe -m pip install -r tools\requirements-console.txt
  if errorlevel 1 goto error
)
.venv-console\Scripts\python.exe tools\passport_console.py
goto end
:error
echo Install Python 3.10+ and try again.
:end
pause
