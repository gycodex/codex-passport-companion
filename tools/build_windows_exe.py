"""Build a standalone Windows EXE and a distributable ZIP without user settings."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/windows-exe')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        parser.error('Build this artifact on Windows x64')
    if importlib.metadata.version('frida') != '17.18.0':
        raise ValueError('Install tools/requirements-build-exe.txt first')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    notices = ROOT / 'build-windows-exe/notices'
    notices.mkdir(parents=True, exist_ok=True)
    for name in ('LICENSE', 'NOTICE'):
        shutil.copy2(ROOT / name, notices / name)
    for source in (ROOT / 'third_party').glob('*LICENSE*'):
        shutil.copy2(source, notices / source.name)
    packages = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name, version = distribution.metadata['Name'], distribution.version
        packages.append({'name': name, 'version': version})
        for file in distribution.files or []:
            if not any(word in file.name.lower() for word in ('license', 'licence', 'copying', 'notice')):
                continue
            source = Path(distribution.locate_file(file))
            if source.is_file():
                destination = notices / 'dependencies' / name / str(file).replace('../', '').replace('\\', '/')
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise ValueError('Python LICENSE.txt not found; retain the runtime license before packaging')
    shutil.copy2(python_license, notices / 'PYTHON-LICENSE.txt')
    (notices / 'DEPENDENCIES.json').write_text(json.dumps(packages, indent=2), encoding='utf-8')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip())
    source_hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted((ROOT / 'tools').rglob('*'))
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py', '.html', '.js', '.css', '.ico', '.spec', '.txt')}
    manifest = dict(version='0.2.5', built_at=datetime.now(timezone.utc).isoformat(),
                    base_commit=revision, uncommitted_sources=dirty, source_sha256=source_hashes,
                    python=platform.python_version(), architecture=platform.machine())
    (notices / 'BUILD.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(output), '--workpath', str(ROOT / 'build-windows-exe/pyinstaller'),
                    str(ROOT / 'tools/passport.spec')], cwd=ROOT, check=True)
    executable = output / 'Passport.exe'
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  Passport.exe\n', encoding='ascii')
    readme = (
        'Passport Windows 桌面版（预览版）\n\n'
        '双击 Passport.exe 即可启动，无需安装 Python 或下载程序依赖。\n'
        '需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime。\n'
        '先打开并登录自己的 Codex，再按照向导连接设备。\n'
        '关闭窗口后仍在托盘运行；使用窗口或托盘菜单中的“退出”停止后台。\n'
        '请把 EXE 放在固定目录，可右键创建快捷方式。托盘可选登录 Windows 时启动。\n'
        '更新前请先退出旧版 Passport 后台；不要在临时解压目录启用登录启动。\n\n'
        '语音需要用户自己的输入法和虚拟音频驱动；程序不包含 Codex、输入法或音频驱动。\n'
        '已包含豆包可选适配所需组件，只有启用该功能时才会申请额外权限。\n'
        '配置与日志默认位于用户目录 .codex/passport-console（支持 CODEX_HOME）。\n'
        '本包只更新电脑端，不刷写设备固件。尚未完成第二台电脑与完整真机验收。\n'
        '构建来源及第三方许可位于 notices。程序未进行代码签名。\n')
    (output / '使用说明.txt').write_text(readme, encoding='utf-8-sig')
    archive = output / 'Passport-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for path in (executable, output / '使用说明.txt', output / 'SHA256SUMS.txt'):
            package.write(path, path.name)
        for path in sorted(notices.rglob('*')):
            if path.is_file():
                package.write(path, 'notices/' + path.relative_to(notices).as_posix())
    print(json.dumps({'exe': str(executable), 'zip': str(archive), 'bytes': executable.stat().st_size,
                      'sha256': digest}, indent=2))


if __name__ == '__main__':
    main()
