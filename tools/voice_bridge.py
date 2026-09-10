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
    if type(cfg["voice_enabled"]) is not bool or type(cfg["voice_hotkeys"]) is not bool:
        raise ValueError("语音设置无效")
    if cfg["voice_ime"] not in ("xunfei", "doubao", "typeless", "custom"):
        raise ValueError("输入法选择无效")
    if not isinstance(cfg["voice_output"], str) or len(cfg["voice_output"]) > 512:
        raise ValueError("虚拟音频设备无效")
    start, stop = parse_shortcut(cfg["voice_start_key"]), parse_shortcut(cfg["voice_stop_key"])
    if cfg["voice_enabled"]:
        if cfg["mode"] != "lan":
            raise ValueError("第一版语音输入需要局域网连接")
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
            channels=self.channels, dtype="int16", blocksize=0, callback=self._callback)
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
        ki=KEYBDINPUT(wVk=0, wScan=0x38, dwFlags=0x09 | (0 if pressed else 0x02))))
    if SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
        raise ValueError("右 Alt 发送失败，请检查输入法与控制台是否以相同权限运行")


class Shortcuts:
    def __init__(self, cfg):
        self.enabled = cfg["voice_hotkeys"] and cfg["voice_output"] != "meter"
        self.start = parse_shortcut(cfg["voice_start_key"])
        self.stop = parse_shortcut(cfg["voice_stop_key"])
        self.keyboard = None
        if self.enabled:
            from pynput.keyboard import Controller, Key
            self.keyboard, self.Key = Controller(), Key

    def send(self, keys):
        if not self.enabled:
            return
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
                key = getattr(self.Key, name) if len(name) > 1 else name
                self.keyboard.press(key)
                pressed.append(key)
            time.sleep(.03)
        finally:
            for key in reversed(pressed):
                self.keyboard.release(key)



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
        while client.is_connected and not stop_requested():
            packet = await client.request(b'{"voice":"poll"}')
            pcm = decode_packet(packet)
            if packet["session"] != session and (packet["recording"] or pcm):
                if started:
                    raise ValueError("语音会话切换异常，请重新连接")
                session, expected = packet["session"], 0
                shortcuts.send(shortcuts.start)
                started = True
            if pcm:
                gap = packet["sequence"] - expected
                if gap < 0 or gap > 100:
                    raise ValueError("语音帧顺序异常，请重新连接")
                # Short losses preserve timing; bounded output drops excess backlog.
                for _ in range(gap):
                    output.push(b'\0' * 640)
                output.push(pcm)
                expected = packet["sequence"] + len(pcm) // 640
            if started and not packet["recording"] and not packet["pending"]:
                await output.drain()
                started = False
                shortcuts.send(shortcuts.stop)
            now = time.monotonic()
            if now - last_report >= .2:
                report("synced", voice=dict(status="recording" if started else "ready",
                    peak=packet["peak"] if started else 0, dropped=packet["dropped"] + output.dropped))
                last_report = now
            await asyncio.sleep(.01 if started else .02)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "语音连接失败，请检查虚拟音频设备和系统权限"
        report("voice_error", message=message, voice=dict(status="error", message=message, peak=0))
    finally:
        if client.is_connected:
            with suppress(Exception):
                await asyncio.wait_for(client.request(b'{"voice":"stop"}'), 1)
        if output:
            await output.drain()
            output.close()
        if started and shortcuts:
            with suppress(Exception):
                shortcuts.send(shortcuts.stop)


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
            try:
                await task
            except asyncio.CancelledError:
                # Swallow the child's cancellation, never the caller's stop request.
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
