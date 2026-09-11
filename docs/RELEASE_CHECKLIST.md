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

## Evidence and limits — latest local check

| Check | Status |
| --- | --- |
| Windows Python 3.12 suite | 49 tests passed, including BLE reply framing, cancellation, audio gaps and authorization |
| Host C suite | 16 tests passed, including voice lease expiry, clipping counters, framing capacity and BLE home controls |
| ESP-IDF 5.5.3 ESP32-C3 build | Passed locally; factory app partition fits and app-only USB flash hash verified. Existing recovery partition overflow warning remains; this image is not for the recovery partition |
| BLE usage and microphone | Connected, microphone ready; user tried recording and described it as usable but imperfect |
| LAN voice | Observed multi-second stalls and dropped audio on this network; not a low-latency guarantee |
| Status bar | Device screenshot verified BLE at top-left, battery at top-right |
| Console restart and BLE reconnect | Verified locally after holding a Windows COM MTA reference on the bridge worker |
| Doubao | Verified Windows x64 0.9.0.0 executable hash only; non-official temporary adapter |
| Clean second Windows computer / macOS / Typeless | NOT RUN |
| 20 reconnect cycles / 30-minute soak | NOT RUN |
| CI for this commit | Must be checked after push; local results are not CI results |

These are observations on one connected device, not acceptance for all boards,
adapters, input methods or networks. Voice capture tolerates a five-second poll
interruption and reports stop reasons; this does not recover missing speech.
BLE audio has bounded framing and requires MTU >=185. The local hardware revision
has not been independently documented; full hardware acceptance remains open.

## Distribution boundaries

Do not include pairing JSON, user settings, console logs, virtual environments,
the Doubao executable, VB-CABLE installers or copied authentication files in a
source archive. Frida is an optional separately installed dependency; its license
and all other dependency licenses continue to apply. See NOTICE and VOICE.md.

Doubao compatibility is experimental. Selecting Doubao preselects a visible
compatibility setting; saving it and accepting required Windows authorization enables a temporary in-process keyboard callback adapter, scoped to Passport's
marked events. It is not an official Doubao API and can stop working after updates.
Do not replace a verified hash/RVA without inspecting and testing the new build.
