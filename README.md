# FoloToy AI Passport · Codex Usage Buddy

[简体中文](README.zh_CN.md) · **English**

This firmware turns FoloToy AI Passport into a private Codex desk companion. It shows the
remaining share of the current 5-hour and 7-day Codex limits as progress bars, shows the
number of active tasks, and displays a six-second **Task complete** celebration when Codex
writes a final answer. The top-right status area also shows the battery level.

Current release: **0.1.0**.

The implementation starts from this repository's `demo/claude-buddy-port` reference and
keeps its bounded state machine, pixel UI, encrypted Nordic UART BLE transport, bonding,
and reconnect behavior. A local bridge translates Codex data into the device protocol.

## Data flow and privacy

```text
Codex app-server ── rate-limit snapshot ─┐
                                         ├─ local Python bridge ── encrypted BLE ── Passport
~/.codex/sessions ─ message metadata ────┘
```

The bridge asks the local Codex app-server for `account/rateLimits/read`. It reads only
JSONL record type, role, and phase from local session files to detect a user turn and a
`final_answer`; it never sends prompt or answer content to the device. The bridge does not
read or copy Codex authentication tokens.

Codex reports usage as percentages rather than absolute message counts, so the screen
shows `LEFT = 100 - usedPercent` for each available window. If the service is temporarily
unavailable when a window resets, the bridge advances to the next period locally and
reconciles after connectivity returns. A never-observed snapshot is shown as unavailable.

## Build and flash the firmware

Use ESP-IDF 5.5.3 and target ESP32-C3:

```bash
get_idf553
idf.py set-target esp32c3
idf.py build
idf.py flash monitor
```

The device advertises as `Codex-<MAC suffix>`. The first encrypted connection displays a
six-digit passkey on the Passport; enter it in the operating system pairing dialog.

## Run the local bridge

Codex CLI must already be installed and signed in. Python 3.10 or newer is recommended.

```bash
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements-codex-bridge.txt
.venv/bin/python tools/codex_bridge.py
```

Useful options:

```bash
# Verify the local Codex usage payload without Bluetooth.
python3 tools/codex_bridge.py --dry-run

# Select one device explicitly when several are nearby.
python3 tools/codex_bridge.py --device Codex-A1B2C3
```

The bridge refreshes usage every 60 seconds, active-task count every two seconds, sends a
heartbeat every 10 seconds, and reconnects automatically after a BLE interruption. Stop
it with `Ctrl+C`.

## Controls

- `UP`: cycle Home → Usage → Info.
- `DOWN`: scroll or change the current sub-page.
- Hold `OK`: open the menu.
- Settings → Unpair: delete the BLE bond after on-device confirmation.

## Tests

```bash
get_idf553
cmake -S tests -B build-host
cmake --build build-host
ctest --test-dir build-host --output-on-failure
python3 -m unittest tests/test_codex_bridge.py
```

Firmware build success is not hardware validation. On-device acceptance must separately
verify pairing, both usage windows, reset countdowns, running/ready state, completion
celebration, reconnect, battery display, and a sustained BLE connection.

## Attribution

The BLE and Buddy application foundation derives from this repository's
`demo/claude-buddy-port` branch, which in turn documents compatibility with Anthropic's
public Hardware Buddy protocol. See [NOTICE](NOTICE) for attribution. The Codex extension
and bridge are not an official OpenAI hardware integration.
