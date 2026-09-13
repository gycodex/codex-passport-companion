"""Single-file EXE entry point. Private roles never start another GUI."""
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    role = "desktop"
    if len(sys.argv) >= 3 and sys.argv[1] == "--passport-role":
        role = sys.argv[2]
        del sys.argv[1:3]
    if role == "backend":
        from run_console_windowless import main
    elif role == "setup":
        from console_setup import main
    elif role == "desktop":
        from passport_desktop import entrypoint as main
    else:
        raise SystemExit("Unknown application role")
    main()


if __name__ == "__main__":
    main()
