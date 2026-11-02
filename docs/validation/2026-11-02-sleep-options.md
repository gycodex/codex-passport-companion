# Sleep options: build and device update, 2026-11-02

Added 10-second and 30-second options without renumbering existing persisted
sleep modes. This initial build retained the five-minute default. A subsequent
[defaults update](2026-11-02-display-defaults.md) sets 30 seconds and brightness
level 1. Active work dims; idle time turns off the backlight.

Environment installed under `E:/Espressif`: ESP-IDF 5.5.3, Espressif RISC-V
GCC 14.2.0, standalone Python 3.12.14, CMake, Ninja and esptool 4.12.0.
Activate with `. E:/Espressif/activate-idf553.ps1`.
SDK submodule sources were extracted from the official v5.5.3 release ZIP
with CRC verification; SDK Git submodule checks are disabled locally because
the ZIP's Git history was omitted. Project source checks remain enabled.

LVGL is pinned to 9.5.0. Resolving the previous caret requirement selected
9.6, which ignored the old 24 KB memory-pool setting in favor of its new
64 KB default. Pinning preserves the existing configuration and RAM budget.

| Check | Result |
| --- | --- |
| Host C tests | PASS: 18/18, including sleep boundaries, menu cycling and persistence |
| Fresh firmware build | PASS: `idf.py -B build-sleep-final build`, fresh directory and configuration |
| Size check | PASS: `idf.py -B build-sleep-final size` |
| Application binary | 1,738,944 bytes; 1,406,784 bytes remain in the 3 MB factory partition |
| Link-time DRAM | 240,756 bytes used; 80,540 bytes remaining |
| Partition layout | Build table matches the device backup byte for byte |
| Flash | PASS: COM3, application only at `0x10000`; esptool verified the data hash |
| Boot | PASS: two USB UI status responses over 30 seconds; no panic, assert or watchdog indicators |
| Physical menu / 10 s and 30 s timing / wake behavior | NOT RUN |
| Secure pairing, reconnect, approvals, audio and battery acceptance | NOT RUN |
| 20 connection cycles and 30-minute connected soak | NOT RUN |

Device: AI Passport, ESP32-C3 silicon revision v1.1, 8 MB embedded flash.
PCB revision was not physically inspected. No bootloader, partition table,
NVS, card identity or recovery partition was flashed.

Host commands used Ninja and `zig cc` (Clang 19.1.7) on Windows:

```powershell
cmake -S tests -B build-host -G Ninja -DCMAKE_C_COMPILER=E:/Espressif/python-env/Lib/site-packages/ziglang/zig.exe -DCMAKE_C_COMPILER_ARG1=cc
cmake --build build-host --parallel 4
ctest --test-dir build-host --output-on-failure
```

Final build has no compiler warnings. Partition-name and recovery-capacity
warnings match the documented layout: this application targets the 3 MB
factory partition, not the protected 1 MB recovery image.

Application SHA-256:
`a5615e4cd11e158f5312fc36f5daf90f6d88092217da86822237e9e523381e05`.

Full 8 MB pre-update backup, SHA-256, flash log and boot log:
`E:/Espressif/device-backups/20261102-sleep/`.
Build and size logs: `E:/Espressif/build-sleep-final.log` and
`E:/Espressif/size-sleep-final.log`.
