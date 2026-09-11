import asyncio
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ble_transport import BleVoiceClient


class BleTests(unittest.IsolatedAsyncioTestCase):
    def client(self, mtu=256):
        raw = SimpleNamespace(is_connected=True, mtu_size=mtu,
            services=SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(max_write_without_response_size=244)))
        return raw, BleVoiceClient(raw)

    async def test_fragmented_reply_ignores_unrelated_status(self):
        raw, client = self.client()
        async def write(*a, **k):
            client.receive(None, b'{"ack":"status"}\n{"voice":')
            client.receive(None, b'1,"recording":false}\n')
        raw.write_gatt_char = write
        self.assertEqual(await client.request(b'{"voice":"poll"}'), {'voice':1,'recording':False})

    async def test_cancelled_request_invalidates_link(self):
        raw, client = self.client()
        started = asyncio.Event()
        async def write(*a, **k): started.set()
        raw.write_gatt_char = write
        task = asyncio.create_task(client.request(b'{"voice":"poll"}'))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        client.receive(None,b'{"voice":1}\n')
        self.assertFalse(client.is_connected)
        self.assertIsNone(client.pending)

    async def test_small_mtu_rejects_voice_before_any_write(self):
        _, client = self.client(23)
        with self.assertRaises(ValueError): await client.request(b'{"voice":"poll"}')

    async def test_notification_buffer_is_bounded(self):
        _, client = self.client()
        client.receive(None, b'x' * 8193)
        self.assertFalse(client.is_connected)
        self.assertEqual(client.buffer, b'')
