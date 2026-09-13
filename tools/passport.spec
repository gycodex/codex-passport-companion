# Run through build_windows_exe.py to include dependency notices and provenance.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'tools/console'), 'console'),
         (str(root / 'build-windows-exe/notices'), 'notices')]
binaries = []
hiddenimports = ['webview.platforms.winforms', 'webview.platforms.edgechromium',
                 'pynput.keyboard._win32', 'pynput.mouse._win32', '_cffi_backend',
                 'bleak.backends.winrt.client', 'bleak.backends.winrt.scanner']
for package in ('frida', 'pythonnet', 'clr_loader'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += imports
datas += collect_data_files('webview')
datas += copy_metadata('frida')

a = Analysis([str(root / 'tools/passport_entry.py')], pathex=[str(root / 'tools')],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'gi', 'gtk', 'qtpy', 'tkinter',
              'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa',
              'webview.platforms.android', 'webview.platforms.cef'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Passport',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(root / 'tools/console/passport.ico'),
    version=str(root / 'tools/passport_version.txt'))
