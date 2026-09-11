"""Create allowlisted release archives from a clean checkout and matching CI firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(folder, target):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                name = (Path(folder.name) / path.relative_to(folder)).as_posix()
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o100755 if path.suffix == ".command" else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                output.writestr(info, path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--firmware-dir", required=True, type=Path)
    parser.add_argument("--firmware-commit", required=True)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--idf-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
        raise ValueError("Commit the release sources before packaging")
    if args.firmware_commit != revision:
        raise ValueError("Firmware must come from CI for the current source commit")
    if not (args.runtime_dir / "python313._pth").is_file() or (args.runtime_dir / "pyvenv.cfg").exists():
        raise ValueError("Use the clean embedded Python runtime, not a virtual environment")
    description = json.loads((args.firmware_dir / "project_description.json").read_text())
    app = args.firmware_dir / "FoloToy-AI-Passport.bin"
    if description["project_version"] != args.version or app.read_bytes()[48:80].split(b"\0")[0].decode() != args.version:
        raise ValueError("Firmware version does not match the release")
    args.output.mkdir(parents=True, exist_ok=False)
    stage = args.output / "staging"
    desktop = stage / f"passport-desktop-source-v{args.version}"
    portable = stage / f"passport-windows-x64-v{args.version}"
    firmware = stage / f"passport-firmware-v{args.version}"
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for name in tracked:
        path = Path(name)
        include = name in ("README.md", "README.zh_CN.md", "LICENSE", "NOTICE", "start-console.cmd",
                           "start-console.vbs", "start-console.command", "flash-firmware.cmd", "flash-firmware.command")
        include |= name.startswith(("docs/", "third_party/", "tools/console/"))
        include |= len(path.parts) == 2 and path.parts[0] == "tools" and path.suffix in (".py", ".ps1", ".txt")
        if name and include:
            destination = desktop / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
    shutil.copytree(desktop, portable)
    # This is a freshly downloaded official embedded runtime, never a user virtualenv.
    # pip's cross-install console wrappers point to the build interpreter; use python -m instead.
    shutil.copytree(args.runtime_dir, portable / "runtime", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "bin"))
    files = {"FoloToy-AI-Passport.bin": app,
             "bootloader.bin": args.firmware_dir / "bootloader/bootloader.bin",
             "partition-table.bin": args.firmware_dir / "partition_table/partition-table.bin"}
    manifest = {"version": args.version, "commit": revision, "chip": "esp32c3", "app_offset": "0x10000",
                "sha256": {name: sha256(path) for name, path in files.items()}}
    for folder in (portable, firmware):
        (folder / "firmware").mkdir(parents=True)
        for name, source in files.items():
            shutil.copy2(source, folder / "firmware" / name)
        (folder / "firmware/manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        for label, source_root in (("esp-idf", args.idf_dir), ("managed_components", ROOT / "managed_components")):
            for source in source_root.rglob("*"):
                if source.is_file() and source.name.lower().startswith(("license", "licence", "copying", "notice")):
                    destination = folder / "firmware/THIRD_PARTY_LICENSES" / label / source.relative_to(source_root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    for name in ("LICENSE", "NOTICE", "flash-firmware.cmd", "flash-firmware.command",
                 "tools/flash_firmware.py", "docs/DOWNLOADS.md", "third_party/xiabill-ai-passport-LICENSE"):
        destination = firmware / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    for folder in (desktop, portable, firmware):
        (folder / "VERSION.json").write_text(json.dumps({"version": args.version, "commit": revision}, indent=2)+"\n")
        shutil.copy2(ROOT / "docs/DOWNLOADS.md", folder / "START-HERE.md")
    packages = subprocess.check_output([str((portable / "runtime/python.exe").resolve()), "-m", "pip", "list", "--format=json"], text=True)
    (portable / "DEPENDENCIES.json").write_text(packages, encoding="utf-8")
    (portable / "RUNTIME-NOTICE.txt").write_text(
        "Official CPython 3.13.15 embeddable x64 runtime, SHA-256 verified at download.\n"
        "https://www.python.org/downloads/release/python-31315/\n"
        "Python license: runtime/LICENSE.txt. Dependency licenses are retained in\n"
        "runtime/Lib/site-packages/*.dist-info (including licenses subdirectories).\n"
        "See DEPENDENCIES.json for exact bundled versions. Optional Frida, Codex,\n"
        "VB-CABLE, BlackHole and input methods are NOT bundled.\n", encoding="utf-8")
    for folder in (desktop, portable, firmware):
        archive(folder, args.output / (folder.name + ".zip"))
    checksums = "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(args.output.glob("*.zip")))
    (args.output / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
    print(checksums)


if __name__ == "__main__":
    main()
