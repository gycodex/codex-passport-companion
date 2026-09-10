#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv-console/bin/python ]; then
  python3 -m venv .venv-console
fi
if ! .venv-console/bin/python -c 'import bleak, cryptography' 2>/dev/null; then
  .venv-console/bin/python -m pip install -r tools/requirements-console.txt
fi
exec .venv-console/bin/python tools/passport_console.py
