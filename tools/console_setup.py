"""User-authorized Windows console restart; no firmware changes."""
import ctypes
import getpass
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from desktop_runtime import child_environment, command, frozen


def needs_setup(cfg):
    if not (sys.platform == 'win32' and cfg.get('voice_enabled') and
            cfg.get('voice_hotkeys') and cfg.get('voice_ime') == 'doubao' and
            cfg.get('voice_doubao_compat') and cfg.get('voice_output') != 'meter'):
        return False
    try:
        return not ctypes.windll.shell32.IsUserAnAdmin() or importlib.metadata.version('frida') != '17.18.0'
    except importlib.metadata.PackageNotFoundError:
        return True


def launch(port, directory, token):
    if sys.platform != 'win32':
        raise ValueError('豆包授权仅支持 Windows')
    args = command("setup", port, directory.resolve(), token, getpass.getuser())
    shell = ctypes.windll.shell32.ShellExecuteW
    shell.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                      ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.restype = ctypes.c_void_p
    previous = os.environ.get("PYINSTALLER_RESET_ENVIRONMENT")
    try:
        if frozen():
            os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        result = shell(None, 'runas', args[0], subprocess.list2cmdline(args[1:]), str(directory.resolve()), 0)
    finally:
        if previous is None:
            os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
        else:
            os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = previous
    if not result or result <= 32:
        raise ValueError('未完成 Windows 授权，后台保持运行，可以重试')


def main():
    port, directory, token, user = sys.argv[1:]
    directory = Path(directory)
    # Alternate administrator credentials must never switch Codex accounts.
    result_path = directory / 'setup-result.json'
    def report(message):
        result_path.write_text(json.dumps({'message': message}, ensure_ascii=False), encoding='utf-8')
    base = 'http://127.0.0.1:' + str(int(port))
    if getpass.getuser().casefold() != user.casefold():
        report('授权失败：请使用当前 Windows 用户授权，不能切换其他管理员账户')
        return
    try:
        report('正在准备豆包组件…')
        try:
            installed = importlib.metadata.version('frida') == '17.18.0'
        except importlib.metadata.PackageNotFoundError:
            installed = False
        if not installed:
            if frozen():
                raise ValueError("EXE 缺少匹配的豆包组件，请重新下载完整版本")
            with (directory / 'setup.log').open('a', encoding='utf-8') as log:
                subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(Path(__file__).with_name('requirements-doubao.txt'))],
                               stdout=log, stderr=log, check=True, timeout=180,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        # Prepare before stopping the old service; failures leave it usable.
        report('正在切换后台并重新连接…')
        req = urllib.request.Request(base + '/api/exit', data=b'{}',
            headers={'X-Passport-Token': token, 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=25).close()
        for _ in range(80):
            try:
                urllib.request.urlopen(base + '/health', timeout=.5).close()
            except OSError:
                break
            time.sleep(.25)
        else:
            raise ValueError('旧后台未退出，请重试')
        subprocess.Popen(command("backend", '--port', port, '--config-dir', directory, '--connect'),
            env=child_environment(), creationflags=subprocess.CREATE_NO_WINDOW)
        report('正在启动已授权后台…')
    except Exception:
        import traceback
        with (directory / 'setup.log').open('a', encoding='utf-8') as log:
            traceback.print_exc(file=log)
        report('豆包准备失败，请重试；详细原因见本机 setup.log')


if __name__ == '__main__':
    main()
