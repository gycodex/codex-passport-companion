"""Back up and update the factory application on a matching AI Passport board."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def validate_bundle(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name in ("FoloToy-AI-Passport.bin", "partition-table.bin"):
        actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if actual != manifest["sha256"][name]:
            raise ValueError("Firmware checksum mismatch: " + name)
    size = (folder / "FoloToy-AI-Passport.bin").stat().st_size
    if not 0 < size <= 0x300000:
        raise ValueError("Firmware does not fit the factory application partition")
    return manifest


def validate_partition(actual, expected):
    if len(expected) < 32 or actual[:len(expected)] != expected:
        raise ValueError("Board partition layout differs from this release. Nothing was flashed.")


def reset_device(port):
    import serial
    from esptool.reset import HardReset
    connection = serial.Serial()
    connection.port, connection.baudrate = port, 115200
    connection.dtr = connection.rts = False
    try:
        connection.open()
        HardReset(connection, uses_usb=True)()
        time.sleep(.5)
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="USB serial port, e.g. COM3 or /dev/cu.usbmodem...")
    parser.add_argument("--list", action="store_true", help="List ports without resetting or flashing")
    parser.add_argument("--check-only", action="store_true", help="Read and validate the board layout only")
    parser.add_argument("--yes", action="store_true", help="Confirm the selected device update")
    args = parser.parse_args()
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    for port in ports:
        print(f"{port.device}: {port.description}")
    if args.list:
        return
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    folder = root / "firmware"
    manifest = validate_bundle(folder)
    if not args.port:
        candidates = [p.device for p in ports if p.vid == 0x303A and p.pid == 0x1001]
        args.port = candidates[0] if len(candidates) == 1 else input("Passport USB port: ").strip()
    if args.port not in [p.device for p in ports]:
        raise ValueError("Choose a connected serial port from the list above")
    print(f"AI Passport ESP32-C3 / {manifest['version']} / {args.port}")
    print("请先退出 Passport 电脑程序和串口监视器。")
    print("升级前自动备份原固件；保留 Wi-Fi、配对信息和恢复分区。")
    if not args.check_only and not args.yes and input("确认设备后，输入 FLASH 并回车开始升级：").strip() != "FLASH":
        print("Cancelled.")
        return
    backup = folder.parent / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    def command(*arguments):
        with (backup / "flash.log").open("a", encoding="utf-8") as log:
            prefix = [sys.executable, "--esptool"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "esptool"]
            result = subprocess.run([*prefix, "--chip", "esp32c3",
                "--port", args.port, "--baud", "460800", "--after", "no_reset", *arguments],
                stdout=log, stderr=subprocess.STDOUT,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
        if result.returncode:
            raise RuntimeError("USB operation failed. See " + str(backup / "flash.log"))
    try:
        print("Checking the board partition layout...")
        partition = backup / "partition-table.bin"
        command("read_flash", "0x8000", "0x1000", str(partition))
        validate_partition(partition.read_bytes(), (folder / "partition-table.bin").read_bytes())
        if args.check_only:
            print("Board layout matches; no flash changes made.")
            return
        print("Backing up the original application (about one minute)...")
        original = backup / "original-app.bin"
        command("read_flash", "0x10000", "0x300000", str(original))
        if original.stat().st_size != 0x300000:
            raise RuntimeError("Incomplete backup; update cancelled")
        (backup / "original-app.sha256").write_text(hashlib.sha256(original.read_bytes()).hexdigest()+"\n")
        print("Writing and verifying the new application...")
        command("write_flash", "0x10000", str(folder / "FoloToy-AI-Passport.bin"))
        print("Update verified. Backup: " + str(backup))
    finally:
        reset_device(args.port)


if __name__ == "__main__" and getattr(sys, "frozen", False) and sys.argv[1:2] == ["--esptool"]:
    import esptool
    esptool.main(sys.argv[2:])
elif __name__ == "__main__":
    interactive = getattr(sys, "frozen", False) and len(sys.argv) == 1
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print("Update stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    finally:
        if interactive:
            try:
                input("\n操作已结束，按回车关闭窗口。")
            except EOFError:
                pass
