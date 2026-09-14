import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import sys
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from lan_pairing import Pairing, derive, parse_discovery, discover
from unittest.mock import patch, AsyncMock, MagicMock
import socket
from types import SimpleNamespace

DOMAIN = b'FAP-PAIR-1:'
IDENTITY = '001122aabbcc'
PSK = bytes(range(32))

class DiscoveryTests(unittest.TestCase):
    def test_targeted_discovery_validates_and_sends_only_to_target(self):
        for host in ('bad', '8.8.8.8', '127.0.0.1', '0.0.0.0', '224.0.0.1'):
            with self.assertRaises(ValueError):
                asyncio.run(discover(host=host))

        async def check():
            loop = asyncio.get_running_loop()
            send = AsyncMock()
            receive = AsyncMock(side_effect=asyncio.TimeoutError)
            socket_module = SimpleNamespace(**vars(socket))
            socket_module.socket = MagicMock()
            with patch('lan_pairing.socket', socket_module):
                with patch.object(loop, 'sock_sendto', send), patch.object(loop, 'sock_recvfrom', receive):
                    self.assertEqual(await discover(host='10.99.5.232'), [])
            self.assertEqual(send.await_count, 1)
            self.assertEqual(send.call_args.args[2], ('10.99.5.232', 8764))
        asyncio.run(check())

    def test_valid_and_untrusted_discovery(self):
        value = dict(app='passport', v=1, nonce='ab'*8, id=IDENTITY, port=8765, pair=True)
        self.assertEqual(parse_discovery(json.dumps(value), '192.168.1.2', value['nonce'])['name'], 'Passport-AABBCC')
        for changes in [dict(nonce='ff'*8), dict(id='x'), dict(port=80), dict(pair=1), dict(app='other')]:
            with self.assertRaises(ValueError):
                parse_discovery(json.dumps(dict(value, **changes)), '192.168.1.2', value['nonce'])
        for payload, address in [('[]','192.168.1.2'), (json.dumps(value),'8.8.8.8'), ('x'*257,'192.168.1.2')]:
            with self.assertRaises(ValueError): parse_discovery(payload,address,value['nonce'])

class PairingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mode = 'good'
        self.approved = asyncio.Event()
        self.finished = asyncio.Event()
        self.errors = []
        self.server = await asyncio.start_server(self.device, '127.0.0.1', 0)
        self.pair = Pairing()
        self.address = dict(host='127.0.0.1', port=self.server.sockets[0].getsockname()[1], id=IDENTITY, name='Test Passport')

    async def asyncTearDown(self):
        await self.pair.close()
        self.approved.set()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.wait_for(self.finished.wait(), 2)
        if self.errors: raise self.errors[0]

    async def device(self, reader, writer):
        try:
            commitment = (await reader.readline()).decode().strip().split(' ')[1]
            private = ec.derive_private_key(7, ec.SECP256R1())
            public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            nonce = bytes(range(16))
            identity = 'ffffffffffff' if self.mode == 'wrong_id' else IDENTITY
            hello = f'FAP_PAIR1 {public.hex()} {nonce.hex()} {identity}\n'.encode()
            # Exercise consecutive TCP fragments, including the final newline.
            for start in range(0,len(hello),7):
                writer.write(hello[start:start+7]); await writer.drain(); await asyncio.sleep(0)
            reveal = await reader.readline()
            if not reveal: return
            _, cpub, cnonce = reveal.decode().strip().split(' ')
            cpub, cnonce = bytes.fromhex(cpub), bytes.fromhex(cnonce)
            self.assertEqual(commitment, hashlib.sha256(DOMAIN+b'commit'+cpub+cnonce).hexdigest())
            shared = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),cpub))
            # Independent HKDF implementation mirrors firmware's extract / expand.
            digest = hashlib.sha256(DOMAIN+cpub+public+cnonce+nonce+IDENTITY.encode()).digest()
            prk = hmac.new(digest, shared, hashlib.sha256).digest()
            key = hmac.new(prk, DOMAIN+b'key\x01', hashlib.sha256).digest()
            self.code = f"{int.from_bytes(hmac.new(key, DOMAIN+b'sas', hashlib.sha256).digest()[:4],'big')%1000000:06d}"
            writer.write(b'FAP_READY1\n'); await writer.drain()
            proof = await reader.readline()
            if not proof: return
            self.assertEqual(proof, b'FAP_CONFIRM1 '+hmac.new(key,DOMAIN+b'confirm',hashlib.sha256).hexdigest().encode()+b'\n')
            await self.approved.wait()
            if self.mode == 'deny': return
            iv = bytes(range(12))
            encrypted = AESGCM(key).encrypt(iv,PSK,digest)
            if self.mode == 'tamper': encrypted = encrypted[:-1]+bytes([encrypted[-1]^1])
            writer.write(b'FAP_KEY1 '+iv.hex().encode()+b' '+encrypted.hex().encode()+b'\n'); await writer.drain()
        except (ConnectionError, asyncio.CancelledError): pass
        except Exception as error: self.errors.append(error)
        finally:
            writer.close()
            await writer.wait_closed()
            self.finished.set()

    async def test_two_confirmations_and_fragmented_exchange(self):
        public = await self.pair.start(self.address)
        self.assertEqual(public['code'], self.code)
        pending = asyncio.create_task(self.pair.confirm(public['id']))
        await asyncio.sleep(.03)
        self.assertFalse(pending.done())
        self.approved.set()
        result = await pending
        self.assertEqual(result,dict(key=PSK.hex(),device_id=IDENTITY))
        self.assertIsNone(self.pair.key)

    async def test_stale_session_and_expiry_cannot_confirm(self):
        await self.pair.start(self.address)
        with self.assertRaises(ValueError): await self.pair.confirm('stale')
        self.pair.deadline = asyncio.get_running_loop().time()-1
        with self.assertRaises(ValueError): await self.pair.confirm(self.pair.id)

    async def test_wrong_identity_rejected_before_reveal(self):
        self.mode='wrong_id'
        with self.assertRaises(ValueError): await self.pair.start(self.address)
        self.assertIsNone(self.pair.key)

    async def test_tampered_key_rejected(self):
        self.mode='tamper'
        await self.pair.start(self.address)
        self.approved.set()
        with self.assertRaises(InvalidTag): await self.pair.confirm(self.pair.id)
        self.assertIsNone(self.pair.key)

    async def test_device_denial_never_returns_key(self):
        self.mode='deny'
        await self.pair.start(self.address)
        self.approved.set()
        with self.assertRaises(ValueError): await self.pair.confirm(self.pair.id)

    async def test_cancel_closes_connection(self):
        await self.pair.start(self.address)
        await self.pair.close()
        await asyncio.wait_for(self.finished.wait(),2)
        self.assertIsNone(self.pair.key)


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        import threading
        from collections import deque
        from unittest.mock import AsyncMock
        from passport_console import Controller
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller.__new__(Controller)
        c = self.controller
        c.directory = Path(self.temp.name)
        c.lock = threading.RLock()
        c.action_lock = asyncio.Lock()
        c.config = dict(mode='lan',host='192.168.1.10',port=8765)
        c.state = {}
        c.logs = deque()
        c.pair_worker = c.pair_expiry = None
        c.perform_action = AsyncMock(return_value={'ok':True})
        c.pair = self.pair = Pairing()
        self.pair.id = 'current'
        self.pair.device = dict(host='192.168.1.20',port=8765)
        self.pair.confirm = AsyncMock(return_value=dict(key=PSK.hex(),device_id=IDENTITY))
        self.pair.close = AsyncMock()
        c.directory.joinpath('pairing.json').write_text('{"key":"old"}')

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_key_saved_only_after_success_not_in_status(self):
        await self.controller.finish_pair(self.pair)
        saved=json.loads(self.controller.directory.joinpath('pairing.json').read_text())
        self.assertEqual(saved['key'],PSK.hex())
        self.assertNotIn(PSK.hex(),json.dumps(self.controller.snapshot()))
        self.assertEqual(self.controller.config['host'],'192.168.1.20')
        self.controller.perform_action.assert_awaited_once_with('connect',{})

    async def test_failed_confirmation_preserves_previous_key_and_config(self):
        self.pair.confirm.side_effect=ValueError('denied')
        await self.controller.finish_pair(self.pair)
        self.assertEqual(json.loads(self.controller.directory.joinpath('pairing.json').read_text())['key'],'old')
        self.assertEqual(self.controller.config['host'],'192.168.1.10')
        self.controller.perform_action.assert_not_awaited()

    async def test_cancelled_or_replaced_session_cannot_overwrite_pairing(self):
        self.controller.pair=None
        await self.controller.finish_pair(self.pair)
        self.assertEqual(json.loads(self.controller.directory.joinpath('pairing.json').read_text())['key'],'old')
        self.controller.perform_action.assert_not_awaited()

    async def test_cancel_drains_worker_and_clears_session(self):
        self.controller.pair_worker=asyncio.create_task(asyncio.sleep(30))
        await self.controller.cancel_pair()
        self.assertTrue(self.controller.pair_worker.done())
        self.assertIsNone(self.controller.pair)
        self.assertIsNone(self.controller.state['pairing'])

class RediscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_address_change_still_requires_stored_key_authentication(self):
        from unittest.mock import AsyncMock, patch
        from lan_transport import LanClient
        client=LanClient('192.168.1.10',PSK,device_id=IDENTITY)
        addresses=[]
        async def authenticate():
            addresses.append(client.host)
            self.assertEqual(client.key,PSK)
            if client.host!='192.168.1.30': raise ValueError('authentication failed')
            return client
        client.connect_at=authenticate
        devices=[dict(id='ffffffffffff',host='192.168.1.99'),dict(id=IDENTITY,host='192.168.1.20'),dict(id=IDENTITY,host='192.168.1.30')]
        with patch('lan_pairing.discover',AsyncMock(return_value=devices)):
            self.assertIs(await client.__aenter__(),client)
        self.assertEqual(addresses,['192.168.1.10','192.168.1.20','192.168.1.30'])

    async def test_discovered_impostor_not_trusted(self):
        from unittest.mock import AsyncMock, patch
        from lan_transport import LanClient
        client=LanClient('192.168.1.10',PSK,device_id=IDENTITY)
        client.connect_at=AsyncMock(side_effect=ValueError('wrong key'))
        with patch('lan_pairing.discover',AsyncMock(return_value=[dict(id=IDENTITY,host='192.168.1.20')])):
            with self.assertRaises(ConnectionError): await client.__aenter__()
        self.assertFalse(client.is_connected)

if __name__ == '__main__': unittest.main()
