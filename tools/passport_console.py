"""Local-only browser control panel. Run with Python 3.10 or newer."""
import argparse
import asyncio
from collections import deque
import copy
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import threading
import time
import webbrowser
import urllib.request

from codex_bridge import bridge_loop, NUS_SERVICE_UUID

ASSETS = Path(__file__).with_name("console")


def running_codex_paths():
    """Inspect only this user's Codex processes; never retain command arguments."""
    try:
        import psutil
    except ImportError:
        return []
    candidates = []
    try:
        owner = psutil.Process().username()
        deadline = time.monotonic() + 3
        for process in psutil.process_iter(["name"]):
            if time.monotonic() >= deadline:
                break
            try:
                if (process.info.get("name") or "").lower() not in ("codex", "codex.exe"):
                    continue
                if process.username() != owner:
                    continue
                executable = process.exe()
                arguments = process.cmdline()
                normalized = executable.replace("\\", "/").lower()
                server = "app-server" in arguments[1:]
                # Desktop GUI can also be named Codex.exe. Require CLI evidence.
                vendor_cli = "/vendor/" in normalized and "/codex/" in normalized
                if server or vendor_cli:
                    candidates.append((0 if server else 1, executable))
            except (psutil.Error, OSError):
                continue
    except (psutil.Error, OSError):
        return []
    return [path for _, path in sorted(set(candidates))]


def find_codex():
    for executable in running_codex_paths():
        if Path(executable).is_file() and os.access(executable, os.X_OK):
            return executable
    found = shutil.which("codex")
    candidates = []
    if sys.platform == "win32":
        npm = Path(os.environ.get("APPDATA", "")) / "npm"
        roots = [npm]
        if found:
            roots.insert(0, Path(found).parent)
        for root in roots:
            candidates.extend(root.glob("node_modules/@openai/codex/node_modules/@openai/codex-win32-*/vendor/*/codex/codex.exe"))
            candidates.extend(root.glob("node_modules/@openai/codex/vendor/*/codex/codex.exe"))
        if found and Path(found).suffix.lower() == ".exe":
            candidates.insert(0, Path(found))
    else:
        if found:
            candidates.append(Path(found))
        # Finder launches do not necessarily inherit the user's terminal PATH.
        candidates.extend(Path(p) for p in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"))
        candidates.extend([Path.home()/".local/bin/codex", Path.home()/".npm-global/bin/codex"])
        candidates.extend(sorted((Path.home()/".nvm/versions/node").glob("*/bin/codex"), reverse=True))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "codex"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(value, stream, ensure_ascii=False)
    temp.replace(path)


class Controller:
    def __init__(self, directory):
        self.directory = directory
        self.lock = threading.RLock()
        self.config = dict(mode="lan", host="", port=8765, device="", codex="", codex_auto=True, autoconnect=False,
            voice_enabled=False, voice_output="", voice_ime="xunfei",
            voice_start_key="f6", voice_stop_key="f6", voice_hotkeys=True, voice_doubao_compat=False)
        try:
            saved = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
            self.config.update({k: saved[k] for k in self.config if k in saved})
        except (OSError, ValueError):
            pass
        self.state = dict(status="disconnected", running=0, usage={}, synced_at=None)
        self.logs = deque(maxlen=150)
        self.test_pending = False
        self.last_test = 0
        self.task = None
        self.stop_requested = False
        self.loop = asyncio.new_event_loop()
        self.action_lock = asyncio.Lock()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def report(self, kind, **data):
        with self.lock:
            if kind in ("starting", "connecting", "connected", "retrying", "disconnected", "error", "stopping"):
                self.state["status"] = kind
            self.state.update({k: v for k, v in data.items() if k != "message"})
            if kind != "synced":
                # Backend exceptions can contain transport details; expose only their class.
                message = data.get("message", kind)
                if kind in ("retrying", "error"):
                    message = message.split(":", 1)[0] + ": check device, network and Codex login"
                self.logs.append(dict(at=time.time(), kind=kind, message=message[:240]))

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(dict(**self.state, config=self.config,
                key_present=(self.directory / "pairing.json").exists(), logs=list(self.logs)))

    def take_test(self):
        with self.lock:
            pending, self.test_pending = self.test_pending, False
            return pending

    async def action(self, name, data):
        async with self.action_lock:
            return await self.perform_action(name, data)

    async def perform_action(self, name, data):
        if name == "save":
            if self.task and not self.task.done():
                raise ValueError("Disconnect before changing settings")
            cfg = dict(self.config)
            for key in cfg:
                if key in data:
                    cfg[key] = data[key]
            if cfg["mode"] not in ("lan", "ble"):
                raise ValueError("Invalid transport")
            for key in ("host", "device", "codex"):
                if not isinstance(cfg[key], str) or len(cfg[key]) > 1024:
                    raise ValueError("Invalid setting")
                cfg[key] = cfg[key].strip()
            if cfg["host"]:
                address = ipaddress.IPv4Address(cfg["host"])
                if not (address.is_private or address.is_link_local):
                    raise ValueError("Use a local IPv4 address")
            if type(cfg["port"]) is not int or not 1 <= cfg["port"] <= 65535:
                raise ValueError("Invalid port")
            if type(cfg["autoconnect"]) is not bool:
                raise ValueError("Invalid autoconnect setting")
            if type(cfg["codex_auto"]) is not bool:
                raise ValueError("Invalid setting")
            from voice_bridge import validate_config
            validate_config(cfg)
            pairing = data.get("pairing")
            if pairing is not None:
                if not isinstance(pairing, dict) or not isinstance(pairing.get("key"), str):
                    raise ValueError("Invalid pairing file")
                if len(pairing["key"]) != 64 or len(bytes.fromhex(pairing["key"])) != 32:
                    raise ValueError("Invalid pairing key")
                atomic_json(self.directory / "pairing.json", {"key": pairing["key"]})
            atomic_json(self.directory / "settings.json", cfg)
            with self.lock:
                self.config = cfg
            self.report("saved", message="Settings saved on this computer")
        elif name == "connect":
            if self.task and not self.task.done():
                return {"ok": True}
            cfg = dict(self.config)
            if cfg["mode"] == "lan" and (not cfg["host"] or not (self.directory / "pairing.json").exists()):
                raise ValueError("Enter device IP and import pairing file first")
            args = argparse.Namespace(lan=cfg["host"] if cfg["mode"] == "lan" else None,
                lan_port=cfg["port"], lan_key_file=str(self.directory / "pairing.json"),
                device=cfg["device"] or None,
                codex=find_codex() if cfg["codex_auto"] or not cfg["codex"] else cfg["codex"], dry_run=False)
            self.test_pending = False
            self.stop_requested = False
            self.report("starting")
            self.task = asyncio.create_task(self.run_bridge(args))
        elif name == "disconnect":
            self.stop_requested = True
            self.report("stopping")
            if self.task and not self.task.done():
                self.task.cancel()
                done, _ = await asyncio.wait({self.task}, timeout=10)
                if not done:
                    self.task.cancel()
                    done, _ = await asyncio.wait({self.task}, timeout=3)
                if not done:
                    self.report("error", message="Disconnect timed out")
                    raise ValueError("断开超时，请退出后台后重新启动")
                try:
                    self.task.result()
                except asyncio.CancelledError:
                    pass
            self.test_pending = False
            self.report("disconnected", voice=dict(status="off", peak=0))
        elif name == "test":
            with self.lock:
                if self.state["status"] != "connected":
                    raise ValueError("Connect first")
                if time.monotonic() - self.last_test < 5:
                    raise ValueError("Please wait five seconds between tests")
                self.last_test = time.monotonic()
                self.test_pending = True
        elif name == "voice_devices":
            from voice_bridge import output_devices
            # PortAudio/WASAPI must initialize and open streams on the same thread.
            return {"devices": output_devices()}
        elif name == "scan":
            if self.task and not self.task.done():
                raise ValueError("Disconnect before scanning")
            from bleak import BleakScanner
            devices = await BleakScanner.discover(timeout=8, service_uuids=[NUS_SERVICE_UUID])
            return {"devices": [{"name": d.name or "AI Passport", "address": d.address} for d in devices]}
        else:
            raise ValueError("Unknown action")
        return {"ok": True}

    async def run_bridge(self, args):
        try:
            await bridge_loop(args, self)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.report("error", message=type(error).__name__)

    def submit(self, name, data):
        return asyncio.run_coroutine_threadsafe(self.action(name, data), self.loop).result(timeout=35)

    def close(self):
        try:
            self.submit("disconnect", {})
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            if not self.thread.is_alive():
                self.loop.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, controller):
        super().__init__(("127.0.0.1", port), Handler)
        self.controller = controller
        self.token = secrets.token_urlsafe(32)
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value, content_type="application/json; charset=utf-8"):
        payload = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self, token=False):
        if self.headers.get("Host") not in self.server.hosts:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in self.server.hosts}:
            return False
        return not token or hmac.compare_digest(self.headers.get("X-Passport-Token", ""), self.server.token)

    def do_GET(self):
        if not self.authorized(self.path.startswith("/api/")):
            return self.reply(403, {"error": "Forbidden"})
        if self.path == "/api/status":
            return self.reply(200, self.server.controller.snapshot())
        if self.path == "/health":
            return self.reply(200, {"app": "passport-companion-console"})
        assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
        if self.path not in assets:
            return self.reply(404, {"error": "Not found"})
        name, mime = assets[self.path]
        content = (ASSETS / name).read_bytes().replace(b"__TOKEN__", self.server.token.encode())
        self.reply(200, content, mime + "; charset=utf-8")

    def do_POST(self):
        if not self.authorized(True):
            return self.reply(403, {"error": "Forbidden"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                return self.reply(413, {"error": "Invalid request size"})
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or not self.path.startswith("/api/"):
                raise ValueError("Invalid request")
            if self.path == "/api/exit":
                self.reply(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            result = self.server.controller.submit(self.path[5:], data)
            self.reply(200, result)
        except ValueError as error:
            self.reply(400, {"error": str(error)[:160]})
        except Exception as error:
            self.reply(500, {"error": type(error).__name__ + ": operation failed"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--config-dir", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "passport-console")
    args = parser.parse_args()
    controller = Controller(args.config_dir)
    try:
        server = Server(args.port, controller)
    except OSError:
        controller.close()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=2) as response:
                existing = json.load(response)
            if existing.get("app") == "passport-companion-console":
                if not args.no_browser:
                    webbrowser.open(f"http://127.0.0.1:{args.port}/")
                return
        except (OSError, ValueError):
            pass
        print("Port is in use. Open the running console or choose --port.", file=sys.stderr)
        return
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Passport console: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    if controller.config["autoconnect"]:
        try:
            controller.submit("connect", {})
        except ValueError as error:
            controller.report("error", message=str(error))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.close()


if __name__ == "__main__":
    main()
