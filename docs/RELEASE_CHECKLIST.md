# Release review — 2026-09-11

This is a source candidate, not a declaration of completed hardware acceptance.

## Required before a public release

- [ ] Confirm redistribution rights for inherited zt20/codex-usage-ai-passport code.
  Its reviewed default branch has NOTICE but no project-level LICENSE. The MIT
  license added here covers our original contributions, not an upstream grant.
- [ ] Obtain passing results from the new CI workflow: Python 3.10/3.13 on Windows
  and Linux, host C tests, and a fresh ESP-IDF 5.5.3 ESP32-C3 build with size output.
- [ ] Record exact board revision and run the README hardware acceptance checks.
- [ ] Test clean installation on a second Windows computer, including the optional
  administrator launcher, new pairing file and audio device selection.

## Evidence and limits

| Check | Status |
| --- | --- |
| Local Python 3.13 suite | 39 tests passed at this review stage |
| Windows console / LAN / Doubao voice | User confirmed working on this machine before release cleanup |
| Doubao adapter build validation | Exact executable SHA-256, x64 architecture, callback readiness; unsupported builds fail closed |
| Revised opt-in UI / administrator launcher on this machine | Passed; LAN reconnected and microphone ready |
| Optional installation on a clean machine | NOT RUN |
| Fresh local host C suite / firmware build / size inspection | NOT RUN: no local IDF_PATH, idf.py, CMake or C compiler; Docker daemon unavailable |
| New CI workflow | Added; result must be checked after push |
| macOS / other Doubao versions / second PC | NOT RUN |
| 20 reconnect cycles / 30-minute soak | NOT RUN |

The user accepts current voice latency. One diagnostic sample measured 171 ms
median poll time, a 901 ms maximum, up to 390 ms of queued output and 14 dropped
frames. These are observations from one session, not performance guarantees.
Desktop file scans now run outside the audio event loop, and queued device audio
is fetched without an extra polling sleep. Firmware was not changed in this review.

## Distribution boundaries

Do not include pairing JSON, user settings, console logs, virtual environments,
the Doubao executable, VB-CABLE installers or copied authentication files in a
source archive. Frida is an optional separately installed dependency; its license
and all other dependency licenses continue to apply. See NOTICE and VOICE.md.

Doubao compatibility is experimental and disabled by default. An explicit setting
enables a temporary in-process keyboard callback adapter, scoped to Passport's
marked events. It is not an official Doubao API and can stop working after updates.
Do not replace a verified hash/RVA without inspecting and testing the new build.
