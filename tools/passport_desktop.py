"""Windows desktop shell. The existing authenticated local service owns BLE/audio."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from desktop_runtime import child_environment, command, frozen, redirect_log


class Instance:
    """One window per user/port; another launch signals the existing window."""
    def __init__(self, port):
        key = hashlib.sha256(f"{getpass.getuser()}:{port}".encode()).hexdigest()[:24]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        for name in ("CloseHandle", "SetEvent"):
            getattr(self.kernel, name).argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.mutex = self.kernel.CreateMutexW(None, False, "Local\\Passport-" + key)
        self.existing = ctypes.get_last_error() == 183
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.event = self.kernel.CreateEventW(None, False, False, "Local\\Passport-show-" + key)
        if not self.event:
            self.kernel.CloseHandle(self.mutex)
            raise ctypes.WinError(ctypes.get_last_error())
        if self.existing:
            self.kernel.SetEvent(self.event)

    def requested(self):
        return self.kernel.WaitForSingleObject(self.event, 0) == 0

    def close(self):
        self.kernel.CloseHandle(self.event)
        self.kernel.CloseHandle(self.mutex)


class Backend:
    def __init__(self, port, directory):
        self.port, self.directory = port, directory
        self.url = f"http://127.0.0.1:{port}/"
        self.token = None
        self.process = None
        # Loopback requests must never be routed through an environment proxy.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, data=None, timeout=None):
        headers = {"X-Passport-Token": self.token or ""}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path,
            data=None if data is None else json.dumps(data).encode(), headers=headers)
        limit = timeout if timeout is not None else (20 if data is not None else 2)
        with self.http.open(request, timeout=limit) as response:
            return json.load(response)

    def attach(self):
        health = self.request("health")
        if health.get("app") != "passport-companion-console":
            raise ValueError("本机端口被其他程序占用，请关闭占用程序后重试。")
        if health.get("desktop_api") != 1:
            raise ValueError("检测到旧版 Passport 后台。请先在原控制台点击“退出”，再打开桌面版。")
        with self.http.open(self.url, timeout=2) as response:
            html = response.read(262144).decode("utf-8")
        match = re.search(r'name="passport-token" content="([A-Za-z0-9_-]+)"', html)
        if not match:
            raise ValueError("后台版本不兼容，请退出旧版 Passport 后重试。")
        previous, self.token = self.token, match[1]
        return previous is not None and previous != self.token

    def start(self):
        try:
            self.attach()
            return
        except urllib.error.HTTPError:
            raise
        except (OSError, urllib.error.URLError):
            pass
        self.process = subprocess.Popen(command("backend", "--port", self.port,
            "--config-dir", self.directory.resolve()), env=child_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(180):
            try:
                self.attach()
                return
            except urllib.error.HTTPError:
                raise
            except (OSError, urllib.error.URLError):
                if self.process.poll() is not None:
                    raise RuntimeError("后台启动失败，请查看配置目录中的 console.log。")
                time.sleep(.25)
        raise RuntimeError("后台启动超时，请查看配置目录中的 console.log。")

    def status(self):
        try:
            return self.request("api/status"), False
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
            changed = self.attach()
            return self.request("api/status"), changed

    def stop(self):
        try:
            self.attach()
            self.request("api/exit", {}, timeout=5)
        finally:
            # Only a child started by this desktop instance may be terminated.
            if self.process and self.process.poll() is None:
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=2)


def icon_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 8, 60, 55), radius=12, fill="#345c3a")
    draw.rectangle((17, 23, 23, 30), fill="#e6f4bf")
    draw.rectangle((41, 23, 47, 30), fill="#e6f4bf")
    draw.rectangle((24, 40, 40, 44), fill="#e6f4bf")
    return image


def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            command, _ = winreg.QueryValueEx(key, "PassportCompanion")
            return command == startup_command()
    except OSError:
        return False


def startup_command():
    if frozen():
        return subprocess.list2cmdline(command("desktop"))
    launcher = Path(__file__).resolve().parents[1] / "start-console.vbs"
    executable = Path(os.environ["WINDIR"]) / "System32/wscript.exe"
    return subprocess.list2cmdline([str(executable), str(launcher)])


def set_startup(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "PassportCompanion", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "PassportCompanion")
            except FileNotFoundError:
                pass


class Desktop:
    def __init__(self, backend, instance):
        self.backend, self.instance = backend, instance
        self.window = self.tray = None
        self.finished = threading.Event()
        self.quitting = threading.Lock()
        self.tray_ready = False

    def show(self, *_):
        self.window.show()
        self.window.restore()

    def toggle_startup(self, *_):
        try:
            set_startup(not startup_enabled())
        except OSError:
            self.show()
            self.window.create_confirmation_dialog("未能保存设置", "无法修改当前用户的登录启动项，请稍后重试。")

    def closing(self):
        if not self.finished.is_set():
            if self.tray_ready:
                self.window.hide()
            else:
                threading.Thread(target=self.quit, daemon=True).start()
            return False

    def quit(self, *_):
        if not self.quitting.acquire(blocking=False):
            return
        try:
            self.backend.stop()
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            try:
                self.finished.set()
                self.window.destroy()
            finally:
                self.quitting.release()

    def watch(self):
        while not self.finished.wait(2):
            if self.instance.requested():
                self.show()
            try:
                state, changed = self.backend.status()
                if changed:
                    self.window.load_url(self.backend.url)
                labels = {"connected": "已连接", "connecting": "正在连接", "starting": "正在启动",
                          "retrying": "正在重连", "disconnected": "未连接", "error": "连接异常"}
                self.tray.title = "Passport · " + labels.get(state["status"], "正在处理")
            except (OSError, ValueError, urllib.error.URLError):
                # Keep the shell alive while the authorized voice backend restarts.
                self.tray.title = "Passport · 后台暂不可用"

    def run(self):
        import webview
        import pystray
        desktop = self

        class WindowApi:
            # Only expose lifecycle, never arbitrary filesystem/process methods.
            def quit(self):
                threading.Thread(target=desktop.quit, daemon=True).start()

        self.window = webview.create_window("Passport 桌面伙伴", self.backend.url,
            js_api=WindowApi(), width=1080, height=800, min_size=(760, 600),
            background_color="#eceee5", text_select=True)
        self.window.events.closing += self.closing
        self.tray = pystray.Icon("Passport", icon_image(), "Passport · 正在启动",
            pystray.Menu(pystray.MenuItem("打开 Passport", self.show, default=True),
                         pystray.MenuItem("登录 Windows 时启动", self.toggle_startup, checked=lambda _: startup_enabled()),
                         pystray.MenuItem("退出 Passport", lambda *_: threading.Thread(target=self.quit, daemon=True).start())))

        def ready(icon):
            icon.visible = True
            self.tray_ready = True

        try:
            self.tray.run_detached(ready)
            webview.start(self.watch, gui="edgechromium", private_mode=True,
                          icon=str(Path(__file__).with_name("console") / "passport.ico"))
        finally:
            self.finished.set()
            self.tray.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--config-dir", type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "passport-console")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("桌面版目前支持 Windows；其他系统请使用 start-console.command。")
    instance = Instance(args.port)
    backend = Backend(args.port, args.config_dir)
    try:
        if instance.existing:
            return
        backend.start()
        Desktop(backend, instance).run()
    except Exception:
        if backend.process is not None:
            try:
                backend.stop()
            except Exception:
                pass
        raise
    finally:
        instance.close()


def entrypoint():
    # pythonw has no console; retain diagnostics and show an actionable message.
    from desktop_runtime import config_directory
    directory = config_directory()
    if sys.stdout is None:
        redirect_log("desktop")
    try:
        main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        help_text = ("请安装 Microsoft Edge WebView2 Runtime 后重试。\n" if frozen() else
                     "可运行 start-console.cmd 查看错误；也可用 start-browser.cmd 打开网页版。\n")
        ctypes.windll.user32.MessageBoxW(None,
            f"Passport 未能启动：{error}\n请确认已安装 Microsoft Edge WebView2 Runtime。\n"
            + help_text +
            f"日志：{directory / 'desktop.log'}", "Passport 桌面伙伴", 0x10)
        sys.exit(1)


if __name__ == "__main__":
    entrypoint()
