"""Serialized NUS writes and bounded voice replies over a paired BLE link."""
import asyncio
import json
from contextlib import suppress

RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'


class BleVoiceClient:
    def __init__(self, client):
        self.client = client
        self.lock = asyncio.Lock()
        self.buffer = bytearray()
        self.pending = None
        self.failed = False

    @property
    def is_connected(self):
        return self.client.is_connected and not self.failed

    def receive(self, _sender, data):
        self.buffer.extend(data)
        if len(self.buffer) > 8192:
            self.failed = True
            self.buffer.clear()
            if self.pending and not self.pending.done():
                self.pending.set_exception(ValueError('蓝牙响应过长，请重新连接'))
            return
        while b'\n' in self.buffer:
            line, _, rest = self.buffer.partition(b'\n')
            self.buffer[:] = rest
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and value.get('voice') == 1 and self.pending and not self.pending.done():
                self.pending.set_result(value)

    async def write(self, payload):
        characteristic = self.client.services.get_characteristic(RX)
        if characteristic is None:
            raise ValueError('未找到设备蓝牙接收通道')
        size = max(20, min(244, characteristic.max_write_without_response_size))
        wire = payload.rstrip(b'\r\n') + b'\n'
        for offset in range(0, len(wire), size):
            await self.client.write_gatt_char(RX, wire[offset:offset+size], response=False)

    async def send_payload(self, payload):
        async with self.lock:
            await self.write(payload)

    async def request(self, payload):
        if payload not in (b'{"voice":"poll"}', b'{"voice":"stop"}'):
            raise ValueError('不支持的蓝牙语音请求')
        if self.client.mtu_size < 185:
            raise ValueError('当前蓝牙数据包过小，无法传输语音；请更新蓝牙驱动或使用局域网')
        async with self.lock:
            if not self.is_connected:
                raise ConnectionError('蓝牙已断开')
            self.pending = asyncio.get_running_loop().create_future()
            try:
                await self.write(payload)
                return await asyncio.wait_for(self.pending, 5)
            except BaseException:
                # Never let a late reply satisfy a different request.
                self.failed = True
                raise
            finally:
                self.pending = None

    async def close(self):
        self.failed = True
        self.buffer.clear()
        if self.pending and not self.pending.done():
            self.pending.cancel()
        with suppress(Exception):
            await self.client.stop_notify(TX)
