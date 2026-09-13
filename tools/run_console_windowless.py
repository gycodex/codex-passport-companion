"""Windows pythonw entry point: keep diagnostics when no terminal is attached."""
import sys
import traceback
from desktop_runtime import redirect_log

def main():
    redirect_log("console")
    sys.argv.append("--no-browser")
    try:
        from passport_console import main as run_server
        run_server()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
