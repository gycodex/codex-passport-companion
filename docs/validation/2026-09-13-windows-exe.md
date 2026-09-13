# Standalone Windows EXE — 2026-09-13

Artifact: `dist/windows-exe/Passport.exe`, built with PyInstaller 6.22.2 / Python 3.13.14.
This is a local desktop preview, not the existing v0.2.2 firmware release. The ZIP contains
the executable, Chinese instructions, SHA-256 and dependency notices. The executable also
contains the notices. No user settings, pairing keys or login credentials are bundled.

| Check | Result |
| --- | --- |
| Python suite | PASS — 69 tests, including frozen role dispatch, EXE startup path, isolated child environment and fail-closed optional dependency handling |
| One-file build | PASS — Windows x64, windowed, embedded icon and version resources |
| Independent launch | PASS — copied only Passport.exe into a separate Chinese-named directory; working directory there; PATH limited to Windows/System32 and Windows; PYTHONHOME/PYTHONPATH removed |
| Native WebView2 window | PASS — welcome page rendered from bundled assets |
| Backend startup | PASS — a separate EXE role served authenticated local APIs on isolated port 18768 |
| Audio dependencies | PASS — voice_devices API enumerated virtual outputs; no microphone recording |
| BLE dependencies | PASS — scan API completed without import/DLL errors; no device selected or paired |
| Tray / repeated launch | PASS — closing the window retained backend; launching EXE again restored the existing window and exited with code 0 |
| Exit | PASS — page Exit released the window instance, stopped the backend health endpoint and left zero test EXE processes |
| Source configuration isolation | PASS — test configuration under build-exe-smoke; no existing configuration altered |
| Startup registry / elevated Doubao session | NOT RUN on the user account; command construction and environment restoration covered by tests |
| Actual BLE/LAN connection, voice recognition, long soak | NOT RUN |
| Clean second computer without development tools | NOT RUN; restricted-PATH test does not replace clean-machine acceptance |
| Firmware build / C tests | NOT RUN — no ESP-IDF/CMake here; this change does not modify firmware |
| Code signing | NOT SIGNED |

Build warnings were reviewed: the missing-module inventory contains optional non-Windows
backends and dynamically loaded .NET namespaces. The required Windows window, backend,
audio enumeration and BLE scanning were exercised in the executable.

Implementation references: [PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html),
[independent subprocess environment](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html),
[pywebview freezing](https://pywebview.flowrl.com/guide/freezing).
