"""Windows pythonw entry point: keep diagnostics when no terminal is attached."""
import os
from pathlib import Path
import sys
import traceback

directory = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "passport-console"
directory.mkdir(parents=True, exist_ok=True)
log = directory / "console.log"
if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
    log.replace(directory / "console.previous.log")
sys.stdout = sys.stderr = log.open("a", encoding="utf-8", buffering=1)
sys.argv.append("--no-browser")
try:
    from passport_console import main
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
