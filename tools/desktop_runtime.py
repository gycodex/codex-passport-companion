"""Launch the same roles from source or the standalone Windows executable."""
import os
from pathlib import Path
import sys


def frozen():
    return bool(getattr(sys, "frozen", False))


def command(role, *arguments):
    scripts = {"desktop": "passport_desktop.py", "backend": "run_console_windowless.py",
               "setup": "console_setup.py"}
    if role not in scripts:
        raise ValueError("Unknown application role")
    if frozen():
        prefix = [sys.executable] if role == "desktop" else [sys.executable, "--passport-role", role]
    else:
        prefix = [sys.executable, str(Path(__file__).with_name(scripts[role]))]
    return prefix + [str(argument) for argument in arguments]


def child_environment():
    environment = dict(os.environ)
    if frozen():
        # A backend or elevated helper can outlive its parent. It must own its
        # extraction directory, not reuse files that the parent will remove.
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def config_directory(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    for index, value in enumerate(arguments):
        if value == "--config-dir" and index + 1 < len(arguments):
            return Path(arguments[index + 1]).resolve()
        if value.startswith("--config-dir="):
            return Path(value.split("=", 1)[1]).resolve()
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "passport-console"


def redirect_log(name):
    directory = config_directory()
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / (name + ".log")
    if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
        log.replace(directory / (name + ".previous.log"))
    sys.stdout = sys.stderr = log.open("a", encoding="utf-8", buffering=1)
    return directory
