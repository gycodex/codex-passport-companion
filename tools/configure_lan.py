"""Provision Wi-Fi over physical USB. Passwords are never saved on the computer."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import time

def exchange(port, request, timeout=8):
    port.write(request.encode("utf-8") + b"\n")
    port.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = port.readline()
        if line.startswith(b"FAP_LAN "):
            return json.loads(line[len(b"FAP_LAN "):])
    raise TimeoutError("No LAN response. Check the firmware, USB port and other serial monitors.")

def save_key(path, key):
    path.parent.mkdir(parents=True, exist_ok=True)
    # This is a local pairing key, never a Wi-Fi password or Codex credential.
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump({"key": key}, output); output.write("\n")
    temp.replace(path)

def main():
    parser = argparse.ArgumentParser(description="Configure Passport LAN mode using a USB data cable")
    parser.add_argument("--port", required=True, help="USB serial port, for example COM3")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="Read Wi-Fi IP and connection status")
    mode.add_argument("--disable", action="store_true", help="Forget Wi-Fi and reboot into Bluetooth mode")
    mode.add_argument("--setup", action="store_true", help="Open the phone Wi-Fi setup hotspot")
    mode.add_argument("--transport", choices=("ble", "lan"), help="Switch transport without deleting Wi-Fi pairing")
    parser.add_argument("--key-file", default=str(Path.home()/".codex"/"passport-lan.json"))
    args = parser.parse_args()
    import serial
    config = None
    previous_key = None
    if not args.status and not args.disable and not args.setup and not args.transport:
        ssid = input("2.4 GHz Wi-Fi name (SSID): ")
        password = getpass.getpass("Wi-Fi password (hidden; empty for an open network): ")
        if not 1 <= len(ssid.encode("utf-8")) <= 32 or not (password == "" or 8 <= len(password.encode("utf-8")) <= 63):
            raise ValueError("SSID must be 1–32 UTF-8 bytes; password must be empty or 8–63 bytes")
        config = {"ssid": ssid, "password": password, "key": secrets.token_hex(32)}
    port = serial.Serial()
    port.port, port.baudrate, port.timeout = args.port, 115200, 0.3
    port.dtr = True; port.rts = False
    port.open()
    try:
        # Allow the native USB endpoint to settle after opening it on Windows.
        time.sleep(0.3)
        if args.status:
            print(json.dumps(exchange(port, "FAP_LAN_STATUS_V1"), ensure_ascii=False))
        elif args.transport:
            result = exchange(port, "FAP_LAN_CONFIG_V1 " + json.dumps({"bluetooth": args.transport == "ble"}))
            if not result.get("saved"): raise RuntimeError("Transport switch failed")
            print("Transport saved; restarting without deleting Wi-Fi pairing")
        elif args.setup:
            if not exchange(port, "FAP_LAN_SETUP_V1").get("saved"):
                raise RuntimeError("Could not enter setup mode")
            print("Rebooting into setup. Join Passport Setup with the password shown on the screen.")
            print("Open http://192.168.4.1 on your phone. No network is changed until you save.")
        else:
            if config:
                # Preserve the key before provisioning: a reboot can lose the acknowledgement.
                # Keep the previous key available if this attempt fails.
                path = Path(args.key_file).expanduser()
                if path.exists():
                    backup = path.with_name(path.name + ".previous")
                    previous_key = json.loads(path.read_text(encoding="utf-8"))["key"]
                    save_key(backup, previous_key)
                save_key(path, config["key"])
            result = exchange(port, "FAP_LAN_CONFIG_V1 " + json.dumps(
                {"disable": True} if args.disable else config, ensure_ascii=False))
            if not result.get("saved"):
                if config:
                    if previous_key is not None:
                        save_key(path, previous_key)
                    else:
                        path.unlink(missing_ok=True)
                raise RuntimeError("Device could not save LAN configuration")
            print("Saved. Device is rebooting into " + ("Bluetooth." if args.disable else "LAN mode."))
            if config:
                print("Pairing key saved to:", args.key_file)
                print("After reboot, use --status to read the IP, or open the device network info page.")
    finally:
        port.close()

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.")
