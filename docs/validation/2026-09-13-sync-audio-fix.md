# Task-count and completion-sound fixes after v0.2.3

## Observed failures

- The device accepted encrypted LAN heartbeats and completion events, but reported
  sound_stage=100 and sound_played=0. A captured reboot log showed the RX I2S DMA
  buffer allocation failing with ESP_ERR_NO_MEM.
- A current Windows Codex session contained recent timestamped task records, while
  its filesystem modification time was more than two hours old. Restarting the
  bridge skipped priming this session and incorrectly reported zero active tasks.

## Changes

- Reduced full-duplex I2S buffering from six 240-frame descriptors to four 160-frame
  descriptors per direction: 90 ms to 40 ms at 16 kHz, saving 6,400 bytes during
  initial stereo DMA allocation. Sample rate and codec gain remain unchanged.
- For stale filesystem timestamps, inspect at most 64 KiB of recent record metadata
  before deciding whether to prime a session. Old abandoned sessions remain ignored;
  historical completions do not replay.
- Added the read-only USB FAP_UI_STATUS_V1 diagnostic for current rendered task count,
  completion sequence, heartbeat freshness, page, screen and sound state. It is
  protected by the existing LVGL lock and omits identifiers and credentials.

## Validation

- 85 Python tests and 18 C host tests passed.
- Fresh ESP-IDF 5.5.3 build in build-audio-fix-fresh passed; existing recovery
  partition-name and capacity warnings remain, and only the factory application
  partition is used.
- Application-only flashing on the connected ESP32-C3 passed esptool hash validation.
  After reboot, codec initialization succeeded, sound_stage=5 and sound_played=1.
- One desktop completion test increased the device completion sequence from 18 to 19
  and sound_played from 1 to 2. This verifies playback execution, not a microphone
  measurement of speaker output. Runtime free heap was approximately 15.8 KiB.
- The corrected session watcher recovered one active task from the real local log.
- Rebuilt Windows EXE SHA256:
  057b0b6e2c869c8d9313ad0fb87ddef864fe0448b649fcda93468f16f535a1e8.
- Long-running audio capture under the smaller DMA buffer, 20 reconnect cycles and
  30-minute soak remain NOT RUN. The v0.2.3 tag predates these follow-up fixes.

## Final installed-state check

With the optional voice feature disabled at the user's request, the installed EXE
connected successfully and both the desktop and device reported running=1. Device
heartbeat_stale was false. A final completion test advanced completion_seq from
19 to 20, selected celebration character 6, and increased sound_played from 3 to 4
with sound_stage=5. Free heap was 17,572 bytes with voice disabled.
