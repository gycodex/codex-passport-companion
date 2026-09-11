#!/usr/bin/env python3
"""Bridge local Codex usage and completion events to FoloToy AI Passport."""

from __future__ import annotations

import argparse
from collections import deque
from contextlib import asynccontextmanager, suppress
import asyncio
import json
import os
from pathlib import Path
import sys
import subprocess
import time
from typing import Any

NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
HEARTBEAT_SECONDS = 10.0
USAGE_REFRESH_SECONDS = 60.0
TASK_REFRESH_SECONDS = 2.0
USAGE_CACHE_FILE = "ai-passport-usage-cache.json"
SESSION_PRIME_BYTES = 2 * 1024 * 1024
SESSION_ACTIVE_LOOKBACK_SECONDS = 2 * 60 * 60
INTERRUPTION_NOTICE_SECONDS = 6.0


class CodexAppServer:
    """Small JSONL client for the public Codex app-server protocol."""

    def __init__(self, executable: str = "codex") -> None:
        self.executable = executable
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.next_id = 1
        self.reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            self.executable,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            # Task-list responses can exceed asyncio's default 64 KiB line limit.
            limit=4 * 1024 * 1024,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}),
        )
        self.reader_task = asyncio.create_task(self._read_stdout())
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "folotoy-ai-passport",
                    "title": "FoloToy AI Passport Codex Bridge",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized")

    async def close(self) -> None:
        try:
            if self.process is not None:
                if self.process.stdin is not None:
                    self.process.stdin.close()
                # This is the bridge-owned helper, not the user's Codex app.
                # Closing stdin alone need not make app-server exit.
                if self.process.returncode is None:
                    with suppress(ProcessLookupError):
                        self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError):
                        self.process.kill()
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
        finally:
            if self.reader_task is not None:
                self.reader_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.reader_task
            for future in self.pending.values():
                if not future.done():
                    future.cancel()

    async def request(self, method: str, params: Any = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[request_id] = future
        message: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self._write(message)
        try:
            response = await asyncio.wait_for(future, timeout=15.0)
        finally:
            self.pending.pop(request_id, None)
        if "error" in response:
            raise RuntimeError(f"Codex app-server error for {method}: {response['error']}")
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def notify(self, method: str, params: Any = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self._write(message)

    async def rate_limits(self) -> dict[str, Any]:
        return normalize_rate_limits(await self.request("account/rateLimits/read"))

    async def running_task_count(self) -> int:
        """Count tasks whose current app-server thread status is active."""
        count = 0
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "limit": 100,
                "archived": False,
                "useStateDbOnly": True,
            }
            if cursor is not None:
                params["cursor"] = cursor
            result = await self.request("thread/list", params)
            threads = result.get("data")
            if not isinstance(threads, list):
                break
            for thread in threads:
                if not isinstance(thread, dict):
                    continue
                status = thread.get("status")
                if isinstance(status, dict) and status.get("type") == "active":
                    count += 1
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            cursor = next_cursor
        return count

    async def _write(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Codex app-server is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await self.process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        while line := await self.process.stdout.readline():
            try:
                message = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            request_id = message.get("id")
            future = self.pending.get(request_id)
            if future is not None and not future.done():
                future.set_result(message)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Codex app-server stopped"))


def normalize_rate_limits(response: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, display-safe subset of a rate-limit response."""
    buckets = response.get("rateLimitsByLimitId")
    snapshot = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = response.get("rateLimits")
    if not isinstance(snapshot, dict):
        snapshot = {}

    def window(name: str) -> dict[str, int]:
        value = snapshot.get(name)
        if not isinstance(value, dict):
            return {"used": 0, "duration": 0, "reset": 0}
        return {
            "used": min(100, max(0, int(value.get("usedPercent", 0)))),
            "duration": max(0, int(value.get("windowDurationMins") or 0)),
            "reset": max(0, int(value.get("resetsAt") or 0)),
        }

    return {
        "plan": str(snapshot.get("planType") or "unknown")[:31],
        "primary": window("primary"),
        "secondary": window("secondary"),
        "available": bool(snapshot.get("primary") or snapshot.get("secondary")),
    }


def roll_expired_usage_windows(
    usage: dict[str, Any], now: int | None = None
) -> bool:
    """Advance expired cached windows and clear their previous-period usage."""
    current_time = int(time.time()) if now is None else now
    changed = False
    for name in ("primary", "secondary"):
        window = usage.get(name)
        if not isinstance(window, dict):
            continue
        duration_seconds = max(0, int(window.get("duration", 0))) * 60
        resets_at = max(0, int(window.get("reset", 0)))
        if duration_seconds == 0 or resets_at == 0 or resets_at > current_time:
            continue
        elapsed_cycles = (current_time - resets_at) // duration_seconds + 1
        window["reset"] = resets_at + elapsed_cycles * duration_seconds
        window["used"] = 0
        changed = True
    return changed


def load_cached_usage(path: Path) -> dict[str, Any]:
    """Load the last valid usage snapshot, or return an unavailable snapshot."""
    fallback = normalize_rate_limits({})
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return fallback
    if not isinstance(cached, dict) or cached.get("available") is not True:
        return fallback
    primary = cached.get("primary")
    secondary = cached.get("secondary")
    if not isinstance(primary, dict) or not isinstance(secondary, dict):
        return fallback
    try:
        return {
            "plan": str(cached.get("plan") or "unknown")[:31],
            "primary": {
                "used": min(100, max(0, int(primary.get("used", 0)))),
                "duration": max(0, int(primary.get("duration", 0))),
                "reset": max(0, int(primary.get("reset", 0))),
            },
            "secondary": {
                "used": min(100, max(0, int(secondary.get("used", 0)))),
                "duration": max(0, int(secondary.get("duration", 0))),
                "reset": max(0, int(secondary.get("reset", 0))),
            },
            "available": True,
        }
    except (ValueError, TypeError):
        return fallback


def save_cached_usage(path: Path, usage: dict[str, Any]) -> None:
    """Atomically preserve only successful usage snapshots."""
    if usage.get("available") is not True:
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(usage, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


class SessionWatcher:
    """Watch only message metadata in Codex JSONL session files."""

    def __init__(self, codex_home: Path) -> None:
        self.sessions = codex_home / "sessions"
        self.state_path = codex_home / "ai-passport-bridge-state.json"
        self.offsets: dict[Path, int] = {}
        self.thread_ids: dict[Path, str] = {}
        self.active_turns: set[tuple[Path, str]] = set()
        self.active_legacy_sessions: set[Path] = set()
        self.event_sessions: set[Path] = set()
        self.aborted_turns: deque[tuple[str, str]] = deque(maxlen=256)
        self.interrupted_until = 0.0
        self.completion_sequence = self._load_sequence()
        recent_cutoff = time.time() - SESSION_ACTIVE_LOOKBACK_SECONDS
        for path in self._files():
            try:
                stat = path.stat()
                self.offsets[path] = stat.st_size
                self._read_thread_id(path)
                if stat.st_mtime >= recent_cutoff:
                    self._prime(path)
            except OSError:
                pass

    @property
    def interrupted(self) -> bool:
        return time.monotonic() < self.interrupted_until

    @property
    def running_count(self) -> int:
        active_threads = {
            self.thread_ids.get(path, str(path)) for path, _turn_id in self.active_turns
        }
        active_threads.update(
            self.thread_ids.get(path, str(path))
            for path in self.active_legacy_sessions - self.event_sessions
        )
        return len(active_threads)

    @property
    def running(self) -> bool:
        return self.running_count > 0

    def _read_thread_id(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as stream:
                for _index, line in zip(range(32), stream):
                    record = json.loads(line)
                    if record.get("type") != "session_meta":
                        continue
                    payload = record.get("payload")
                    thread_id = payload.get("id") if isinstance(payload, dict) else None
                    if isinstance(thread_id, str) and thread_id:
                        self.thread_ids[path] = thread_id
                    return
        except (OSError, UnicodeError, json.JSONDecodeError):
            return

    def _prime(self, path: Path) -> None:
        """Recover recent live state while ignoring old abandoned sessions."""
        size = self.offsets.get(path, 0)
        start = max(0, size - SESSION_PRIME_BYTES)
        with path.open("rb") as stream:
            stream.seek(start)
            if start:
                stream.readline()
            for raw_line in stream:
                try:
                    self._consume(path, raw_line.decode("utf-8"), historical=True)
                except UnicodeError:
                    continue

    def poll(self) -> bool:
        """Read appended records. Return True when display state changed."""
        changed = False
        for path in self._files():
            try:
                size = path.stat().st_size
                offset = self.offsets.get(path, 0)
                if path not in self.thread_ids:
                    self._read_thread_id(path)
                if size < offset:
                    offset = 0
                with path.open("r", encoding="utf-8") as stream:
                    stream.seek(offset)
                    for line in stream:
                        changed = self._consume(path, line) or changed
                    self.offsets[path] = stream.tell()
            except (OSError, UnicodeError):
                continue
        return changed

    def _consume(self, path: Path, line: str, historical: bool = False) -> bool:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return False
        payload = record.get("payload")
        if record.get("type") == "event_msg" and isinstance(payload, dict):
            event_type = payload.get("type")
            turn_id = payload.get("turn_id")
            if (event_type in ("task_started", "task_complete", "turn_aborted")
                    and isinstance(turn_id, str) and turn_id):
                thread_id = self.thread_ids.get(path, str(path))
                terminal_key = (thread_id, turn_id)
                if terminal_key in self.aborted_turns:
                    return False
                if event_type == "turn_aborted":
                    # Only retire the matching turn, including mirrored session files.
                    # An old interruption must not clear a newer turn of this thread.
                    matching = {
                        active for active in self.active_turns
                        if self.thread_ids.get(active[0], str(active[0])) == thread_id
                        and active[1] == turn_id
                    }
                    self.aborted_turns.append(terminal_key)
                    if not matching:
                        return False
                    self.active_turns.difference_update(matching)
                    if not historical:
                        self.interrupted_until = time.monotonic() + INTERRUPTION_NOTICE_SECONDS
                    return True
                before = self.running_count
                self.event_sessions.add(path)
                self.active_legacy_sessions.discard(path)
                key = (path, turn_id)
                if event_type == "task_started":
                    self.active_turns.add(key)
                else:
                    thread_id = self.thread_ids.get(path, str(path))
                    self.active_turns = {
                        active
                        for active in self.active_turns
                        if self.thread_ids.get(active[0], str(active[0])) != thread_id
                    }
                    if not historical:
                        self.completion_sequence += 1
                        self._save_sequence()
                return self.running_count != before or (
                    event_type == "task_complete" and not historical
                )
        if record.get("type") != "response_item":
            return False
        if not isinstance(payload, dict) or payload.get("type") != "message":
            return False
        if path in self.event_sessions:
            return False
        role = payload.get("role")
        phase = payload.get("phase")
        if role == "user":
            before = self.running_count
            self.active_legacy_sessions.add(path)
            return self.running_count != before
        if role == "assistant" and phase == "final_answer":
            self.active_legacy_sessions.discard(path)
            if not historical:
                self.completion_sequence += 1
                self._save_sequence()
            return not historical
        return False

    def _files(self) -> list[Path]:
        try:
            return sorted(self.sessions.rglob("*.jsonl"))
        except OSError:
            return []

    def _load_sequence(self) -> int:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return max(0, int(value.get("completionSequence", 0)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    def _save_sequence(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"completionSequence": self.completion_sequence}) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)


def heartbeat_payload(
    usage: dict[str, Any], watcher: SessionWatcher, running_count: int | None = None,
    completed: bool = False,
) -> bytes:
    primary = usage.get("primary", {})
    secondary = usage.get("secondary", {})
    if running_count is None:
        running_count = watcher.running_count
    if completed:
        message = "任务已完成"
    elif watcher.interrupted:
        message = f"Task interrupted; {running_count} running" if running_count else "Task interrupted"
    else:
        message = "助手正在工作" if running_count else "助手已就绪"
    payload = {
        "total": running_count,
        "running": running_count,
        "waiting": 0,
        "msg": message,
        "entries": [],
        "tokens": 0,
        "tokens_today": 0,
        "codex": {
            "plan": usage.get("plan", "unknown"),
            "primary_used": primary.get("used", 0),
            "primary_window": primary.get("duration", 0),
            "primary_reset": primary.get("reset", 0),
            "secondary_used": secondary.get("used", 0),
            "secondary_window": secondary.get("duration", 0),
            "secondary_reset": secondary.get("reset", 0),
            "completion_seq": watcher.completion_sequence,
            "available": bool(usage.get("available")),
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"


async def send_payload(client: Any, payload: bytes) -> None:
    if hasattr(client, "send_payload"):
        # BLE strips its line delimiter before parsing; LAN has its own frame.
        await client.send_payload(payload.removesuffix(b"\n").removesuffix(b"\r"))
        return
    characteristic = client.services.get_characteristic(NUS_RX_UUID)
    if characteristic is None:
        raise RuntimeError("Codex Buddy RX characteristic is missing")
    chunk_size = max(20, int(getattr(characteristic, "max_write_without_response_size", 20)))
    for offset in range(0, len(payload), chunk_size):
        await client.write_gatt_char(
            NUS_RX_UUID, payload[offset : offset + chunk_size], response=False
        )


async def find_device(device_name: str | None) -> Any:
    from bleak import BleakScanner

    print("Scanning for Codex Buddy…", flush=True)
    devices = await BleakScanner.discover(timeout=8.0, service_uuids=[NUS_SERVICE_UUID])
    for device in devices:
        if device_name and (device.name == device_name or device.address == device_name):
            return device
        if not device_name and (device.name or "").startswith("Codex-"):
            return device
    raise RuntimeError("No Codex-* AI Passport found")


@asynccontextmanager
async def open_transport(args):
    if args.lan:
        from lan_transport import LanClient, load_key
        print(f"Connecting to LAN device {args.lan}:{args.lan_port}…", flush=True)
        async with LanClient(args.lan, load_key(args.lan_key_file), args.lan_port) as client:
            yield client
    else:
        from bleak import BleakClient
        device = await find_device(args.device)
        print(f"Connecting to {device.name or device.address}…", flush=True)
        options = {"winrt": {"use_cached_services": True}} if sys.platform == "win32" else {}
        async with BleakClient(device, pair=True, timeout=60.0, **options) as client:
            from ble_transport import BleVoiceClient
            transport = BleVoiceClient(client)
            await client.start_notify(NUS_TX_UUID, transport.receive)
            try:
                yield transport
            finally:
                await transport.close()


async def bridge_loop(args: argparse.Namespace, control=None) -> None:
    def report(kind, **data):
        if control is not None:
            control.report(kind, **data)

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    usage_cache_path = codex_home / USAGE_CACHE_FILE
    watcher = SessionWatcher(codex_home)
    app_server = CodexAppServer(args.codex)
    try:
        report("starting")
        await app_server.start()
        usage = load_cached_usage(usage_cache_path)
        running_count = 0
        try:
            refreshed_usage = await app_server.rate_limits()
            if refreshed_usage.get("available"):
                usage = refreshed_usage
                save_cached_usage(usage_cache_path, usage)
        except Exception as error:
            print(
                f"Codex usage is temporarily unavailable: {error}. Will retry…",
                file=sys.stderr,
                flush=True,
            )
        if roll_expired_usage_windows(usage):
            save_cached_usage(usage_cache_path, usage)
        try:
            running_count = await app_server.running_task_count()
        except Exception as error:
            print(
                f"Codex task count is temporarily unavailable: {error}. Will retry…",
                file=sys.stderr,
                flush=True,
            )
        server_running_count = running_count
        running_count = max(server_running_count, watcher.running_count)
        print(f"用量数据：可用={bool(usage.get('available'))}", flush=True)
        for name in ("primary", "secondary"):
            window = usage.get(name, {})
            duration = window.get("duration", 0)
            if duration > 0:
                print(f"窗口 {duration} 分钟：已用 {window.get('used', 0)}%", flush=True)
        print(f"正在进行的任务：{running_count}", flush=True)
        if args.dry_run:
            print(heartbeat_payload(usage, watcher, running_count).decode().rstrip())
            return
        while not (control is not None and getattr(control, "stop_requested", False)):
            try:
                report("connecting")
                async with open_transport(args) as client:
                    print("Connected. Codex usage and completion alerts are live.", flush=True)
                    timezone_offset = int(
                        time.mktime(time.localtime()) - time.mktime(time.gmtime())
                    )
                    await send_payload(
                        client,
                        json.dumps({"time": [int(time.time()), timezone_offset]}).encode()
                        + b"\n",
                    )
                    last_heartbeat = 0.0
                    last_usage = 0.0
                    last_task_refresh = 0.0
                    # Recover offline changes as a baseline, without replaying alerts.
                    await asyncio.to_thread(watcher.poll)
                    running_count = max(server_running_count, watcher.running_count)
                    previous_sequence = watcher.completion_sequence
                    watcher.interrupted_until = 0.0
                    previous_interrupted = False
                    # Establish the session baseline before enabling test alerts.
                    await send_payload(client, heartbeat_payload(usage, watcher, running_count))
                    report("connected", usage=usage, running=running_count, synced_at=time.time())
                    from voice_bridge import voice_session
                    async with voice_session(client, control):
                        while client.is_connected and not (control is not None and getattr(control, "stop_requested", False)):
                            # File scans must not pause the LAN microphone polling task.
                            interruption_baseline = watcher.interrupted_until
                            changed = await asyncio.to_thread(watcher.poll)
                            new_interruption = watcher.interrupted_until > interruption_baseline
                            interrupted = watcher.interrupted
                            changed = changed or interrupted != previous_interrupted
                            previous_interrupted = interrupted
                            refreshed_count = max(server_running_count, watcher.running_count)
                            changed = changed or refreshed_count != running_count
                            running_count = refreshed_count
                            if control is not None and control.take_test():
                                watcher.completion_sequence += 1
                                watcher._save_sequence()
                                changed = True
                            completed = watcher.completion_sequence > previous_sequence
                            previous_sequence = watcher.completion_sequence
                            now = time.monotonic()
                            if roll_expired_usage_windows(usage):
                                save_cached_usage(usage_cache_path, usage)
                                changed = True
                            if now - last_usage >= USAGE_REFRESH_SECONDS:
                                try:
                                    refreshed_usage = await app_server.rate_limits()
                                    if refreshed_usage.get("available"):
                                        usage = refreshed_usage
                                        roll_expired_usage_windows(usage)
                                        save_cached_usage(usage_cache_path, usage)
                                except Exception as error:
                                    report("warning", message=f"Usage refresh failed: {type(error).__name__}; will retry")
                                    print(
                                        f"Codex usage refresh failed: {error}. Will retry…",
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                last_usage = now
                                changed = True
                            if now - last_task_refresh >= TASK_REFRESH_SECONDS:
                                try:
                                    server_running_count = await app_server.running_task_count()
                                    refreshed_count = max(
                                        server_running_count, watcher.running_count
                                    )
                                    changed = changed or refreshed_count != running_count
                                    running_count = refreshed_count
                                except Exception as error:
                                    report("warning", message=f"Task refresh failed: {type(error).__name__}; will retry")
                                    print(
                                        f"Codex task-count refresh failed: {error}. Will retry…",
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                last_task_refresh = now
                            if changed or now - last_heartbeat >= HEARTBEAT_SECONDS:
                                # Slow account refreshes must not consume the notice before sending.
                                if new_interruption:
                                    watcher.interrupted_until = time.monotonic() + INTERRUPTION_NOTICE_SECONDS
                                await send_payload(
                                    client,
                                    heartbeat_payload(usage, watcher, running_count, completed),
                                )
                                last_heartbeat = now
                                report("synced", usage=usage, running=running_count, synced_at=time.time())
                                if completed:
                                    report("completion", message="Completion sent; sound follows device volume and quiet hours")
                            await asyncio.sleep(1.0)
            except Exception as error:  # BLE backend errors vary by operating system.
                if control is not None and getattr(control, "stop_requested", False):
                    break
                report("retrying", message=f"{type(error).__name__}: {error}" or "连接中断")
                print(f"Bridge disconnected: {error}. Retrying…", file=sys.stderr, flush=True)
                await asyncio.sleep(3.0)
    finally:
        await app_server.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show Codex usage and task-completion alerts on FoloToy AI Passport"
    )
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--device", help="exact BLE device name or address")
    transport.add_argument("--lan", metavar="IP", help="connect over encrypted local Wi-Fi")
    parser.add_argument("--lan-port", type=int, default=8765)
    parser.add_argument("--lan-key-file", default=str(Path.home()/".codex"/"passport-lan.json"))
    parser.add_argument("--codex", default="codex", help="path to the Codex CLI executable")
    parser.add_argument(
        "--dry-run", action="store_true", help="print one sanitized payload without using BLE"
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(bridge_loop(parse_args()))
    except KeyboardInterrupt:
        pass
