"""Physical-button LAN microphone -> virtual cable -> user's speech input shortcut.

Audio lives in a bounded RAM queue only. No transcription service or audio files.
"""
import asyncio
import struct
import base64
from collections import deque
from contextlib import asynccontextmanager, suppress
import threading
import time
import sys
from doubao_compat import MARKER


def parse_shortcut(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("语音快捷键格式无效")
    keys = value.lower().replace(" ", "").split("+") if value else []
    aliases = {"右alt": "alt_r", "rightalt": "alt_r", "ralt": "alt_r"}
    keys = [aliases.get(key, key) for key in keys]
    modifiers = {"ctrl", "alt", "shift", "cmd", "alt_r"}
    allowed = modifiers | {"space"} | {f"f{i}" for i in range(1, 13)} | set("abcdefghijklmnopqrstuvwxyz0123456789")
    if len(keys) > 5 or len(set(keys)) != len(keys) or any(k not in allowed for k in keys):
        raise ValueError("语音快捷键格式无效；支持右 Alt、F1–F12、空格和修饰键组合")
    if keys and keys != ["alt_r"] and sum(k not in modifiers for k in keys) != 1:
        raise ValueError("快捷键需要一个主键")
    return keys


def validate_config(cfg):
    if type(cfg.get("voice_doubao_compat", False)) is not bool:
        raise ValueError("豆包适配设置无效")
    if type(cfg["voice_enabled"]) is not bool or type(cfg["voice_hotkeys"]) is not bool:
        raise ValueError("语音设置无效")
    if cfg["voice_ime"] not in ("xunfei", "doubao", "typeless", "custom"):
        raise ValueError("输入法选择无效")
    if not isinstance(cfg["voice_output"], str) or len(cfg["voice_output"]) > 512:
        raise ValueError("虚拟音频设备无效")
    start, stop = parse_shortcut(cfg["voice_start_key"]), parse_shortcut(cfg["voice_stop_key"])
    if cfg["voice_enabled"]:
        if not cfg["voice_output"]:
            raise ValueError("请先选择虚拟音频设备")
        if cfg["voice_hotkeys"] and (not start or not stop):
            raise ValueError("请填写开始和结束快捷键")


def output_devices():
    import sounddevice as sd
    apis = sd.query_hostapis()
    result = []
    for i, device in enumerate(sd.query_devices()):
        name, api = device["name"], apis[device["hostapi"]]["name"]
        # No default speaker fallback: that would play private dictation aloud.
        if device["max_output_channels"] and ("cable input" in name.lower() or "blackhole" in name.lower()):
            result.append(dict(id=api + ":" + name, name=name, api=api, index=i))
    return sorted(result, key=lambda d: ("WASAPI" not in d["api"], d["name"]))


class MeterOutput:
    """Diagnostic mode discards decoded samples without opening an audio device."""
    dropped = 0
    def push(self, pcm): pass
    async def drain(self): pass
    def close(self): pass


class AudioOutput:
    def __init__(self, identity):
        import numpy as np
        import sounddevice as sd
        selected = [d for d in output_devices() if d["id"] == identity]
        if len(selected) != 1:
            raise ValueError("找不到已选择的虚拟音频设备，请刷新后重新选择")
        device = selected[0]["index"]
        info = sd.query_devices(device)
        self.rate = int(info["default_samplerate"])
        if self.rate not in (16000, 32000, 44100, 48000, 96000):
            raise ValueError("虚拟音频设备采样率不受支持，请设为 48000 Hz")
        self.channels = min(2, info["max_output_channels"])
        self.np, self.lock = np, threading.Lock()
        self.queue = deque()
        self.buffered = 0
        self.dropped = 0
        self.stream = sd.RawOutputStream(device=device, samplerate=self.rate,
            channels=self.channels, dtype="int16", blocksize=0, latency="low", callback=self._callback)
        try:
            self.stream.start()
        except BaseException:
            self.stream.close()
            raise

    def _callback(self, outdata, frames, timing, status):
        outdata[:] = b"\0" * len(outdata)
        with self.lock:
            position = 0
            while self.queue and position < len(outdata):
                chunk = self.queue.popleft()
                count = min(len(chunk), len(outdata) - position)
                outdata[position:position + count] = chunk[:count]
                position += count
                self.buffered -= count
                if count < len(chunk):
                    self.queue.appendleft(chunk[count:])

    def push(self, pcm):
        np = self.np
        samples = np.frombuffer(pcm, dtype="<i2")
        if not len(samples):
            return
        # Each packet is an exact multiple of 20 ms, including at 44.1 kHz.
        if self.rate != 16000:
            samples = np.interp(np.arange(len(samples) * self.rate // 16000) * 16000 / self.rate,
                                np.arange(len(samples)), samples).astype("<i2")
        chunk = np.repeat(samples, self.channels).astype("<i2").tobytes()
        with self.lock:
            limit = self.rate * self.channels  # 500 ms of 16-bit PCM.
            while self.queue and self.buffered + len(chunk) > limit:
                self.buffered -= len(self.queue.popleft())
                self.dropped += 1
            self.queue.append(chunk)
            self.buffered += len(chunk)

    async def drain(self):
        deadline = time.monotonic() + 1
        while self.buffered and time.monotonic() < deadline:
            await asyncio.sleep(.02)
        await asyncio.sleep(.15)  # PortAudio/virtual cable tail before closing IME.

    def close(self):
        self.stream.abort()
        self.stream.close()
        with self.lock:
            self.queue.clear()
            self.buffered = 0


def windows_right_alt(pressed):
    """Send the extended physical right-Alt scan code, checking OS acceptance."""
    import ctypes
    from pynput._util.win32 import INPUT, INPUT_union, KEYBDINPUT, SendInput
    # KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY (+ KEYEVENTF_KEYUP).
    event = INPUT(type=INPUT.KEYBOARD, value=INPUT_union(
        ki=KEYBDINPUT(wVk=0, wScan=0x38, dwFlags=0x09 | (0 if pressed else 0x02), dwExtraInfo=MARKER)))
    if SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
        raise ValueError("右 Alt 发送失败，请检查输入法与控制台是否以相同权限运行")


def windows_shortcut_key(name, pressed):
    """Send physical keys; generic Alt does not identify the configured left Alt."""
    import ctypes
    from pynput._util.win32 import INPUT, INPUT_union, KEYBDINPUT, MapVirtualKey, SendInput
    virtual_keys = {"ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4,
                    "alt_r": 0xA5, "cmd": 0x5B, "space": 0x20}
    if name in virtual_keys:
        vk = virtual_keys[name]
    elif name.startswith("f") and name[1:].isdigit():
        vk = 0x70 + int(name[1:]) - 1
    else:
        vk = ord(name.upper())
    scan = MapVirtualKey(vk, MapVirtualKey.MAPVK_VK_TO_VSC)
    if not scan:
        raise ValueError("无法映射语音快捷键")
    flags = 0x08 | (0x01 if name in ("alt_r", "cmd") else 0) | (0 if pressed else 0x02)
    event = INPUT(type=INPUT.KEYBOARD, value=INPUT_union(
        ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, dwExtraInfo=MARKER)))
    if SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
        raise ValueError("语音快捷键发送失败，请检查输入法与控制台是否以相同权限运行")


class Shortcuts:
    def __init__(self, cfg):
        self.enabled = cfg["voice_hotkeys"] and cfg["voice_output"] != "meter"
        self.start = parse_shortcut(cfg["voice_start_key"])
        self.stop = parse_shortcut(cfg["voice_stop_key"])
        self.keyboard = None
        self.compat = None
        if self.enabled:
            from pynput.keyboard import Controller, Key
            self.keyboard, self.Key = Controller(), Key
            if sys.platform == "win32" and cfg.get("voice_ime") == "doubao" and cfg.get("voice_doubao_compat", False):
                from doubao_compat import DoubaoCompatibility
                self.compat = DoubaoCompatibility()
                self.compat.start()

    def close(self):
        if self.compat:
            self.compat.close()

    def send(self, keys):
        if not self.enabled:
            return
        if self.compat:
            self.compat.check()
        if sys.platform == "win32" and keys == ["alt_r"]:
            try:
                windows_right_alt(True)
                time.sleep(.08)
            finally:
                windows_right_alt(False)
            return
        pressed = []
        try:
            for name in keys:
                key = name if sys.platform == "win32" else (getattr(self.Key, name) if len(name) > 1 else name)
                if sys.platform == "win32":
                    windows_shortcut_key(key, True)
                else:
                    self.keyboard.press(key)
                pressed.append(key)
            time.sleep(.08)
        finally:
            release_error = None
            for key in reversed(pressed):
                try:
                    if sys.platform == "win32":
                        windows_shortcut_key(key, False)
                    else:
                        self.keyboard.release(key)
                except Exception as error:
                    release_error = error
            if release_error:
                raise release_error



STEPS = (7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767)
INDEX = (-1, -1, -1, -1, 2, 4, 6, 8) * 2

def decode_adpcm(data, predictor=0, index=0):
    samples = []
    for byte in data:
        for code in (byte & 15, byte >> 4):
            step = STEPS[index]
            delta = (step >> 3) + ((step >> 2) if code & 1 else 0) + ((step >> 1) if code & 2 else 0) + (step if code & 4 else 0)
            predictor = max(-32768, min(32767, predictor + (-delta if code & 8 else delta)))
            index = max(0, min(88, index + INDEX[code]))
            samples.append(predictor)
    return struct.pack('<' + 'h' * len(samples), *samples)

def decode_packet(packet):
    if packet.get("voice") != 1:
        raise ValueError("设备固件尚不支持语音，请更新固件")
    for name in ("session", "sequence", "pending", "peak", "dropped"):
        if type(packet.get(name)) is not int or not 0 <= packet[name] <= 0xffffffff:
            raise ValueError("设备语音数据无效")
    if type(packet.get("recording")) is not bool or packet["pending"] > 16 or packet["peak"] > 32768:
        raise ValueError("设备语音数据无效")
    compressed = "adpcm" in packet
    value = packet.get("adpcm" if compressed else "pcm")
    if not isinstance(value, str) or len(value) > 1740:
        raise ValueError("设备语音数据过大")
    pcm = base64.b64decode(value, validate=True)
    if compressed:
        if len(pcm) > 1304 or len(pcm) % 163:
            raise ValueError("设备压缩音频长度无效")
        chunks = []
        for offset in range(0, len(pcm), 163):
            predictor, index = struct.unpack_from('<hB', pcm, offset)
            if index > 88:
                raise ValueError("设备压缩音频状态无效")
            chunks.append(decode_adpcm(pcm[offset+3:offset+163], predictor, index))
        pcm = b''.join(chunks)
    if len(pcm) > 5120 or len(pcm) % 640:
        raise ValueError("设备语音帧长度无效")
    return pcm


async def voice_loop(client, cfg, report, stop_requested=lambda: False):
    output = shortcuts = None
    started = False
    try:
        output = MeterOutput() if cfg["voice_output"] == "meter" else AudioOutput(cfg["voice_output"])
        shortcuts = Shortcuts(cfg)
        session, expected, last_report = 0, 0, 0
        poll_ms = 0
        while client.is_connected and not stop_requested():
            poll_start = time.monotonic()
            packet = await client.request(b'{"voice":"poll"}')
            poll_ms = round((time.monotonic() - poll_start) * 1000, 1)
            pcm = decode_packet(packet)
            if packet["session"] != session and (packet["recording"] or pcm):
                if started:
                    raise ValueError("语音会话切换异常，请重新连接")
                session, expected = packet["session"], 0
                report("voice_event", message="收到设备录音开始事件")
                shortcuts.send(shortcuts.start)
                report("voice_event", message="开始快捷键已发送" if shortcuts.enabled else "快捷键未启用（仅传输或测试音频）")
                started = True
            if pcm:
                gap = packet["sequence"] - expected
                if gap < 0 or gap > 100:
                    raise ValueError("语音帧顺序异常，请重新连接")
                # The output callback already emitted silence while waiting for the
                # network. Replaying lost frames as silence delays fresh speech twice.
                # Each ADPCM frame carries its own decoder state, so gaps are safe.
                output.push(pcm)
                expected = packet["sequence"] + len(pcm) // 640
            if started and not packet["recording"] and not packet["pending"]:
                await output.drain()
                started = False
                reason = {2: "设备超过 5 秒未收到电脑轮询，已停止录音", 3: "已达到两分钟录音上限", 4: "设备操作或采集异常导致录音停止"}.get(packet.get("stop_reason"))
                if reason: report("voice_event", message=reason)
                shortcuts.send(shortcuts.stop)
                report("voice_event", message="设备录音结束，结束快捷键已发送" if shortcuts.enabled else "设备录音结束")
            now = time.monotonic()
            if now - last_report >= .2:
                report("synced", voice=dict(status="recording" if started else "ready",
                    peak=packet["peak"] if started else 0, dropped=packet["dropped"] + output.dropped,
                    poll_ms=poll_ms, device_pending_ms=packet["pending"] * 20,
                    stop_reason=packet.get("stop_reason", 0),
                    clipped=packet.get("clipped", 0), samples=packet.get("samples", 0),
                    output_pending_ms=round(1000 * getattr(output, "buffered", 0) /
                        (getattr(output, "rate", 16000) * getattr(output, "channels", 1) * 2), 1)))
                last_report = now
            # Drain queued device audio immediately, yielding between requests.
            await asyncio.sleep(0 if packet["pending"] else (.01 if started else .02))
    except asyncio.CancelledError:
        raise
    except Exception as error:
        import traceback
        print("Voice failure:", type(error).__name__, [(frame.name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)], flush=True)
        message = str(error) if isinstance(error, ValueError) else "语音连接失败，请检查虚拟音频设备和系统权限"
        if isinstance(error, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
            from lan_transport import LanRequestTimeout
            message = "设备通信超时或断开，录音已停止，正在重新连接"
            if isinstance(error, LanRequestTimeout):
                print(str(error), flush=True)
                phase = "发送请求" if error.phase == "write" else "等待设备回复"
                message = (f"{phase}超时（{error.elapsed_ms:.0f} ms），"
                           f"电脑事件循环最大延迟 {error.loop_lag_ms:.0f} ms；正在重新连接")
        report("voice_error", message=message, voice=dict(status="error", message=message, peak=0))
    finally:
        try:
            if client.is_connected:
                with suppress(Exception):
                    await asyncio.wait_for(client.request(b'{"voice":"stop"}'), 1)
            if output:
                with suppress(Exception):
                    await output.drain()
        finally:
            if output:
                with suppress(Exception):
                    output.close()
            try:
                if started and shortcuts:
                    with suppress(Exception):
                        shortcuts.send(shortcuts.stop)
            finally:
                if shortcuts and hasattr(shortcuts, "close"):
                    shortcuts.close()


@asynccontextmanager
async def voice_session(client, control):
    task = None
    if control and getattr(control, "config", {}).get("voice_enabled") and hasattr(client, "request"):
        task = asyncio.create_task(voice_loop(client, dict(control.config), control.report,
            lambda: getattr(control, "stop_requested", False)))
    try:
        yield
    finally:
        if task:
            task.cancel()
            async def join_child():
                with suppress(asyncio.CancelledError):
                    await task

            cleanup = asyncio.create_task(join_child())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # Only caller cancellation escapes the shield. Also works on Python 3.10.
                cleanup.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup
                raise
