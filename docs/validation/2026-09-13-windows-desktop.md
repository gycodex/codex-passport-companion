# Windows desktop source validation — 2026-09-13

Scope: Windows desktop shell, first-run setup, status navigation, launchers and packaging
checks. No firmware, BLE transport or audio implementation changes. This source change
is not included in the existing v0.2.2 release archives.

| Check | Result |
| --- | --- |
| Python host suite | PASS — 65 tests, Python 3.13.14, `python -m unittest discover -s tests -p "test_*.py"` |
| JavaScript syntax | PASS — `node --check tools/console/app.js` |
| PowerShell launcher syntax | PASS — PowerShell parser, startup and shortcut scripts |
| Native window and WebView2 | PASS — first-run environment page and device setup rendered on Windows |
| Close to tray | PASS — closing the window retained the backend on isolated port 18766 |
| Repeated launch | PASS — second launch exited successfully and restored the same window |
| Exit from native page | PASS — window instance released and backend health endpoint stopped |
| Icon | PASS — Passport icon shown in the native title bar |
| Backend token rotation | PASS — automated test recovers authentication and reports page reload required |
| Interrupted setup and existing settings | PASS — automated tests require live sync to finish and preserve old transport/preferences |
| Login startup registry / desktop shortcut installation | NOT RUN on the user's account; opt-in code only |
| Actual Doubao privilege transition | NOT RUN; token rotation and failed-stop lifecycle tested without elevation |
| Real BLE/LAN pairing / microphone | NOT RUN for this desktop change |
| New Windows distribution archive / clean second computer | NOT RUN; release packaging now checks native dependencies |
| Host C tests | NOT RUN — no CMake or IDF_PATH in this environment |
| Fresh ESP-IDF 5.5.3 build and size | NOT RUN — idf.py/get_idf553 unavailable; Docker engine also unavailable |
| Board revision / 20 reconnect cycles / 30-minute soak | NOT RUN |

Desktop dependencies exercised: pywebview 6.2.1, pystray 0.19.5, Pillow 12.3.0.
The live UI used a separate `build-desktop-smoke` configuration directory. No existing
pairing files were modified, no device was paired, and no login startup option was enabled.

The first desktop version retains the existing optional voice configuration. It does not
yet automate virtual-audio-driver installation or replace the input method audio chain.
Installation currently creates shortcuts into a portable directory; it is not an EXE/MSI
installer. Windows CI now installs the desktop requirements before the Python suite.
