import asyncio
import base64
from pathlib import Path
import sys
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from voice_bridge import decode_packet, decode_adpcm, parse_shortcut, voice_loop


def packet(**changes):
    value = dict(voice=1, session=1, recording=False, sequence=0,
                 pending=0, peak=0, dropped=0, pcm='')
    value.update(changes)
    return value


class AudioThreadTests(unittest.TestCase):
    def test_device_discovery_uses_bridge_thread_for_wasapi(self):
        from passport_console import Controller
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(Path(directory))
            observed = []
            def discover():
                observed.append(threading.get_ident())
                return []
            try:
                with patch('voice_bridge.output_devices', discover):
                    self.assertEqual(controller.submit('voice_devices', {}), {'devices': []})
                self.assertEqual(observed, [controller.thread.ident])
            finally:
                controller.close()


class ValidationTests(unittest.TestCase):
    def test_shortcuts_exclude_send_and_arbitrary_commands(self):
        self.assertEqual(parse_shortcut('CTRL+Alt+Space'), ['ctrl', 'alt', 'space'])
        self.assertEqual(parse_shortcut('F6'), ['f6'])
        for invalid in ('enter', 'cmd+enter', 'ctrl+ctrl+a', 'f6+f7', 'ctrl', '__import__', 'alt+tab'):
            with self.assertRaises(ValueError):
                parse_shortcut(invalid)

    def test_adpcm_matches_standard_reference(self):
        self.assertEqual(struct.unpack('<8h', decode_adpcm(bytes.fromhex('77ff2143'))),
                         (11,41,-22,-158,-100,-12,101,233))
        self.assertEqual(len(decode_packet(packet(adpcm=base64.b64encode(bytes(326)).decode()))),1280)
        with self.assertRaises(ValueError):
            decode_packet(packet(adpcm=base64.b64encode(bytes(321)).decode()))

    def test_frames_are_bounded_and_typed(self):
        pcm = b'\x01\0' * 640
        self.assertEqual(decode_packet(packet(pcm=base64.b64encode(pcm).decode())), pcm)
        for invalid in (packet(pcm='!!!!'), packet(pcm='A'*1800), packet(recording=1),
                        packet(sequence=-1), packet(pending=17), packet(peak=40000),
                        packet(pcm='AA=='), {'ok': True}):
            with self.assertRaises(ValueError):
                decode_packet(invalid)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_session_drains_before_stop_and_never_retriggers(self):
        events = []
        class Output:
            dropped = 0
            def __init__(self, _): pass
            def push(self, pcm): events.append(('pcm', len(pcm)))
            async def drain(self): events.append('drain')
            def close(self): events.append('close')
        class Keys:
            start, stop = 'start', 'stop'
            def __init__(self, _): pass
            def send(self, key): events.append(key)
        class Client:
            is_connected = True
            responses = iter([packet(pcm=base64.b64encode(bytes(640)).decode()), packet(sequence=1)])
            async def request(self, payload):
                try: return next(self.responses)
                except StopIteration:
                    self.is_connected = False
                    return packet(sequence=1)
        with patch('voice_bridge.AudioOutput', Output), patch('voice_bridge.Shortcuts', Keys):
            await voice_loop(Client(), {'voice_output':'test'}, lambda *a, **k: None)
        self.assertEqual(events[:4], ['start', ('pcm',640), 'drain', 'stop'])
        self.assertEqual(events.count('start'), 1)
        self.assertEqual(events.count('stop'), 1)
        self.assertEqual(events[-1], 'close')

    async def test_disconnect_stops_ime_and_releases_audio(self):
        events = []
        class Output:
            dropped = 0
            def __init__(self, _): pass
            async def drain(self): pass
            def close(self): events.append('close')
        class Keys:
            start, stop = 'start', 'stop'
            def __init__(self, _): pass
            def send(self, key): events.append(key)
        class Client:
            is_connected = True
            async def request(self, payload):
                if events:
                    self.is_connected = False
                    raise ConnectionError()
                return packet(recording=True)
        with patch('voice_bridge.AudioOutput', Output), patch('voice_bridge.Shortcuts', Keys):
            await voice_loop(Client(), {'voice_output':'test'}, lambda *a, **k: None)
        self.assertEqual(events, ['start','close','stop'])


if __name__ == '__main__':
    unittest.main()
