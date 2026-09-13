# Automatic pairing validation — 2026-09-13

Local working-tree preview; ESP32-C3 AI Passport production 8 MB partition layout.
The initial build checks below preceded the physical upgrade. See the follow-up
section for what was subsequently verified; the listed binary hashes belong to the
pre-tag preview, not a rebuilt v0.2.3 release artifact.

## Automated checks

- Python: `.venv-console/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'`: **82 passed**.
- Native C: CMake / Ninja / Zig Clang 21, fresh `build-host-pair`: **18/18 passed**.
- Pairing tests cover bounded discovery validation, fragmented greetings, independent
  HKDF derivation, waiting for both confirmations, stale/expired sessions, wrong
  device id, tampered GCM tags, denial, cancellation, preservation of existing
  pairing on failure, no key in status, and authenticated IP rediscovery.
- C gate tests cover expiry boundaries, stale ids, and duplicate-decision locking.
- ESP-IDF **5.5.3**, target **esp32c3**: fresh `build-pair-fresh` configuration and
  build passed. Initial Windows backslash environment issue was corrected to forward
  slashes; the fresh build then completed. No firmware compiler warnings found.
- Kconfig emitted an unset ESP_IDF_VERSION environment warning from esp_codec_dev.
- Image: **1,738,480 bytes** (`0x1a86f0`), within the 3 MiB factory application
  partition at `0x10000`; **1,407,248 bytes** headroom. IDF's warning that the 1 MiB
  recovery partition is too small is expected: this application must never be
  written to the permanent recovery partition at `0x700000`.
- Static D/IRAM: **240,756 bytes used / 80,540 bytes remaining**. These are link-time
  numbers, not measured runtime heap. Discovery adds a 3 KiB task stack; ephemeral
  pairing crypto uses checked heap allocation and is zeroized/freed after use.

## Desktop artifact

- Windows x64 preview `0.2.2-desktop-preview.2` built with PyInstaller.
- EXE: `dist/windows-pairing/Passport.exe`, **89,078,546 bytes**.
- SHA256: `33e7ebbf19fd641bdbb263c880acfa2b20923e148b6220dc255deea857ada861`.
- New output directory used because the previous EXE was running; its process and
  user configuration were preserved.
- Launched new EXE with isolated config `build-pair-ui` and port 18767. Native
  WebView window, first-run environment detection, next-step navigation and the
  new LAN search entry were verified through Windows accessibility.

## NOT RUN on physical hardware

- Complete cross-implementation P256 pairing, device-screen code comparison, physical
  approval/rejection and stale-button delivery under real timing.
- Wi-Fi hotspot save/restart without download, automatic reconnect after DHCP changes, bonded BLE regression and device-side reset.
- Runtime peak heap/stack under ECDH, allocation failure behavior, 20 reconnect
  cycles and 30-minute soak. Existing README hardware acceptance remains required.

Protocol and security scope: [LAN-PAIRING.md](../LAN-PAIRING.md).

## Physical upgrade follow-up

- One connected ESP32-C3 AI Passport with the matching 8 MB partition layout was
  upgraded over USB. Exact PCB revision was not independently verified.
- The flasher verified the existing partition table, backed up the full 3 MiB
  application, wrote only the application at 0x10000, and verified its hash.
  Bootloader, NVS, cardid and recovery were not written.
- The restarted device answered UDP discovery on the local router. The new
  desktop authenticated API started an actual P256 pairing exchange through
  FAP_READY1 and displayed the confirmation screen.
- The former desktop key did not authenticate this board at the newly discovered
  address. No key was silently replaced; a new physical comparison was requested.
  Completion of both user confirmations and successful post-pair synchronization
  were not observed. A USB status query timed out after the upgrade, although
  discovery and the pairing handshake responded.
- These observations do not replace the remaining hardware acceptance checklist.

## v0.2.3 tag validation

- Re-ran the complete Python suite: **82 passed**; C host suite: **18/18 passed**.
- Fresh ESP-IDF 5.5.3 configuration and build in `build-release-v023`: **PASS**.
- Embedded application version verified as **0.2.3**; image size **1,738,480 bytes**.
- Build retained the existing recovery-name/subtype and recovery-capacity warnings;
  the application is intended solely for the 3 MiB factory partition. No C compiler
  warnings were reported. Static D/IRAM remains 240,756 bytes used / 80,540 remaining.
- This newly versioned build was not flashed again; physical observations above
  refer to the preceding preview build. No v0.2.3 EXE or GitHub assets were published.
