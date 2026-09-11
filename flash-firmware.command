#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv-flash
.venv-flash/bin/python -m pip install 'esptool==4.12.0'
exec .venv-flash/bin/python tools/flash_firmware.py "$@"
