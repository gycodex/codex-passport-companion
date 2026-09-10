import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from cryptography.exceptions import InvalidTag
from lan_transport import LanClient, MAX_PAYLOAD, handshake_digest, server_hello, load_key, nonce_for, seal, unseal

KEY = bytes(range(32))
CHALLENGE = bytes(range(12))

class CryptoTests(unittest.TestCase):
    def test_roundtrip_and_direction_separation(self):
        self.assertEqual(handshake_digest(KEY, CHALLENGE, CHALLENGE).hex(),
                         '818e94f2164c1bc85efba942ea41ba527dbe183671c6b77d7f8fc0e497f7596e')
        self.assertEqual(seal(KEY, CHALLENGE, 1, b'hello'),
                         b'00000001:cebda52c6011065b2f86f259d272c2311c3b6e7e8c\n')
        payload = b'{"time":[123,28800]}'
        frame = seal(KEY, CHALLENGE, 1, payload)
        self.assertEqual(unseal(KEY, CHALLENGE, 1, frame), payload)
        self.assertNotEqual(nonce_for(CHALLENGE, 1), nonce_for(CHALLENGE, 1, True))
        with self.assertRaises(InvalidTag):
            unseal(KEY, CHALLENGE, 1, frame, True)

    def test_tamper_wrong_key_replay_rejected(self):
        frame = seal(KEY, CHALLENGE, 1, b'{}')
        tampered = frame[:-3] + (b'00' if frame[-3:-1] != b'00' else b'01') + b'\n'
        for key, wire in [(KEY, tampered), (bytes(32), frame)]:
            with self.assertRaises(InvalidTag):
                unseal(key, CHALLENGE, 1, wire)
        with self.assertRaises(ValueError):
            unseal(KEY, CHALLENGE, 2, frame)
        with self.assertRaises(InvalidTag):
            unseal(KEY, bytes(12), 1, frame)

    def test_limits_and_counter_exhaustion(self):
        for payload in (b'', b'x'*(MAX_PAYLOAD+1)):
            with self.assertRaises(ValueError): seal(KEY, CHALLENGE, 1, payload)
        for sequence in (0, 0x80000000):
            with self.assertRaises(ValueError): seal(KEY, CHALLENGE, sequence, b'{}')
        with self.assertRaises(ValueError): unseal(KEY, CHALLENGE, 1, b'x'*10000)

    def test_local_key_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'key.json'
            path.write_text(json.dumps({'key': KEY.hex()}))
            self.assertEqual(load_key(str(path)), KEY)
            path.write_text('{"key":"00"}')
            with self.assertRaises(ValueError): load_key(str(path))

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_replayed_server_greeting_sends_no_payload(self):
        received = []
        async def device(reader, writer):
            await reader.readline()
            # A valid greeting captured from a different client challenge must fail.
            writer.write(server_hello(KEY, bytes(12), CHALLENGE)); await writer.drain()
            received.append(await reader.read())
            writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(device, '127.0.0.1', 0)
        async with server:
            with self.assertRaises(ValueError):
                async with LanClient('127.0.0.1', KEY, server.sockets[0].getsockname()[1]):
                    self.fail('Unauthenticated greeting was accepted')
            await asyncio.sleep(0.02)
        self.assertEqual(received, [b''])

    async def test_socket_exchange_and_reconnect(self):
        received = []
        async def device(reader, writer):
            client_nonce = bytes.fromhex(json.loads(await reader.readline())['client_nonce'])
            session = handshake_digest(KEY, client_nonce, CHALLENGE, b'N')[:12]
            writer.write(server_hello(KEY, client_nonce, CHALLENGE))
            await writer.drain()
            try:
                for sequence in (1, 2):
                    wire = await reader.readline()
                    if not wire: break
                    received.append(unseal(KEY, session, sequence, wire))
                    reply = seal(KEY, session, sequence, b'{"ok":true}', True)
                    # Deliberately fragment the reply to exercise TCP framing.
                    writer.write(reply[:7]); await writer.drain()
                    writer.write(reply[7:]); await writer.drain()
            finally:
                writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(device, '127.0.0.1', 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            for _ in range(2):
                async with LanClient('127.0.0.1', KEY, port) as client:
                    await asyncio.gather(client.send_payload(b'{"time":[1,0]}'),
                                         client.send_payload(b'{"time":[2,0]}'))
                self.assertFalse(client.is_connected)
        self.assertEqual(len(received), 4)

    async def test_rejected_and_unauthenticated_ack(self):
        for invalid in (False, True):
            async def device(reader, writer):
                client_nonce = bytes.fromhex(json.loads(await reader.readline())['client_nonce'])
                session = handshake_digest(KEY, client_nonce, CHALLENGE, b'N')[:12]
                writer.write(server_hello(KEY, client_nonce, CHALLENGE))
                await writer.drain(); await reader.readline()
                writer.write(b'{}\n' if invalid else seal(KEY, session, 1, b'{"ok":false}', True))
                await writer.drain(); writer.close(); await writer.wait_closed()
            server = await asyncio.start_server(device, '127.0.0.1', 0)
            async with server:
                async with LanClient('127.0.0.1', KEY, server.sockets[0].getsockname()[1]) as client:
                    with self.assertRaises(ValueError): await client.send_payload(b'{}')
                    self.assertFalse(client.is_connected)

if __name__ == '__main__': unittest.main()
