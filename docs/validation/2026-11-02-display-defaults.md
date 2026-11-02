# Display defaults update, 2026-11-02

Default sleep is 30 seconds. Default brightness is level 1/4 (40% backlight).
Shared constants cover initial state, startup backlight, missing/invalid saved
sleep settings, UI fallback and factory reset. Existing saved sleep choices
remain supported. USB UI status now includes sleep mode and brightness level
to verify the running firmware.

| Check | Result |
| --- | --- |
| Host C tests | PASS: 18/18; default sleep stays on at 29,999 ms, sleeps at 30,000 ms and wakes at 40% |
| Fresh firmware directory | PASS: `idf.py -B build-defaults build` |
| Size | PASS: `idf.py -B build-defaults size` |
| Binary | 1,739,008 bytes; 1,406,720 bytes free in factory partition |
| Link-time DRAM | 240,756 bytes used; 80,540 bytes remaining |
| Partition layout | Matches the device backup |
| Flash | PASS: COM3, application at `0x10000`, hash verified |
| Running device settings | PASS: USB reports sleep mode 5 (30 seconds), brightness level 1 |
| Idle screen state | PASS: on at 10/28 seconds, off at 32/35 seconds after reset |
| Boot observation | PASS: 38 seconds; no panic, assert or watchdog indicators |
| Physical brightness measurement / factory reset / button wake | NOT RUN |
| 20 connection cycles and 30-minute connected soak | NOT RUN |

Device: AI Passport, ESP32-C3 silicon v1.1, 8 MB flash. PCB revision was not
physically inspected. Its current NVS already stored 30-second sleep; NVS was
backed up and read only. Only the application was flashed. Other settings,
bootloader, identity and recovery partitions were preserved.

No compiler warnings. Documented recovery partition naming/capacity warnings
remain; the application fits the 3 MB factory partition.

Firmware SHA-256:
`968685220d57f70f825671d48f0ae4c9f8ceba04a4be2f9f3f0cead4d7fc89af`.

Logs: `E:/Espressif/build-defaults.log`, `E:/Espressif/size-defaults.log` and
`E:/Espressif/device-backups/20261102-defaults/`.
The last directory contains the NVS backup, flash log, boot log and verified
USB status samples in `verified-defaults.json`.
