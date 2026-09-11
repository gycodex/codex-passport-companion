@echo off
cd /d "%~dp0"
if exist "runtime\python.exe" (
  "runtime\python.exe" tools\flash_firmware.py %*
) else (
  echo This package needs Python 3.10+ and esptool 4.12.0.
  echo For a ready-to-run flasher, download the Windows portable release ZIP.
  python tools\flash_firmware.py %*
)
pause
