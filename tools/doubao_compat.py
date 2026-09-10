"""Version-checked, process-local compatibility for marked Passport key events.

Callback located from this build's SetWindowsHookExW(WH_KEYBOARD_LL) call.
Only our own synthetic events are adapted; no executable is patched on disk.
"""
import hashlib
from pathlib import Path
from contextlib import suppress
import sys

MARKER = 0x50415353
BUILD_HASH = "94b17bdca571ac3cd2dafa687b4cb8e3a789cda9d044276483003b0a9e8f77a6"
CALLBACK_RVA = 0x7426C0


class DoubaoCompatibility:
    def __init__(self):
        self.session = self.script = None

    def start(self):
        if self.session:
            return
        if sys.platform != "win32":
            raise ValueError("豆包兼容适配仅支持 Windows")
        try:
            import frida
        except ImportError as error:
            raise ValueError("缺少豆包适配依赖，请退出后台后使用管理员启动器重新启动") from error
        candidates = [p for p in frida.get_local_device().enumerate_processes()
                      if p.name.casefold() == "imeservice.exe"]
        failure = "豆包未启动"
        for process in candidates:
            session = script = None
            try:
                session = frida.attach(process.pid)
                probe = session.create_script("rpc.exports = { path() { return Process.getModuleByName('ImeService.exe').path; }, arch() { return Process.arch; } };")
                try:
                    probe.load()
                    actual = Path(probe.exports_sync.path())
                    arch = probe.exports_sync.arch()
                finally:
                    probe.unload()
                if arch != "x64" or actual.name.casefold() != "imeservice.exe" or hashlib.sha256(actual.read_bytes()).hexdigest() != BUILD_HASH:
                    raise ValueError("豆包版本未验证；请关闭兼容适配并手动触发语音，或使用已验证版本")
                script = session.create_script(f"""
                    const m = Process.getModuleByName('ImeService.exe');
                    Interceptor.attach(m.base.add({CALLBACK_RVA}), {{
                        onEnter(args) {{
                            if (args[0].toInt32() !== 0 || args[2].isNull()) return;
                            const e = args[2];
                            if (!e.add(16).readPointer().equals(ptr({MARKER}))) return;
                            const flags = e.add(8).readU32();
                            if ((flags & 0x10) === 0) return;
                            this.copy = Memory.alloc(24);
                            Memory.copy(this.copy, e, 24);
                            this.copy.add(8).writeU32(flags & ~0x12);
                            this.copy.add(16).writePointer(ptr(0));
                            args[2] = this.copy;
                        }}
                    }});
                    rpc.exports = {{ ready() {{ return true; }} }};
                """)
                script.load()
                if not script.exports_sync.ready():
                    raise ValueError("豆包按键适配未就绪")
                self.session, self.script = session, script
                return
            except Exception as error:
                failure = str(error) if isinstance(error, ValueError) else "豆包适配连接失败，请使用管理员启动器，并确认豆包仍在运行"
                if script:
                    with suppress(Exception):
                        script.unload()
                if session:
                    with suppress(Exception):
                        session.detach()
        raise ValueError(failure)

    def check(self):
        if not self.session or self.session.is_detached:
            raise ValueError("豆包已退出或适配已断开，请重新连接设备")

    def close(self):
        script, session = self.script, self.session
        self.script = self.session = None
        if script:
            with suppress(Exception):
                script.unload()
        if session:
            with suppress(Exception):
                session.detach()
