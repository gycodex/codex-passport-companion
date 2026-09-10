"""Bounded AES-256-GCM transport for the AI Passport LAN mode."""
import asyncio
import json
import hashlib
import hmac
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_PAYLOAD = 2048
PORT = 8765

def handshake_digest(key: bytes, client_nonce: bytes, server_nonce: bytes, domain=b'H') -> bytes:
    if len(client_nonce) != 12 or len(server_nonce) != 12:
        raise ValueError("Invalid handshake nonce")
    return hmac.new(key, b'FAP-LAN-1:' + domain + client_nonce + server_nonce, hashlib.sha256).digest()

def server_hello(key: bytes, client_nonce: bytes, server_nonce: bytes) -> bytes:
    return json.dumps({'v':1, 'nonce':server_nonce.hex(),
                       'auth':handshake_digest(key, client_nonce, server_nonce).hex()}).encode()+b'\n'

def nonce_for(challenge: bytes, sequence: int, response: bool = False) -> bytes:
    if len(challenge) != 12 or not 0 < sequence < 0x80000000:
        raise ValueError("Invalid LAN nonce or sequence")
    counter = sequence | (0x80000000 if response else 0)
    return challenge[:8] + (int.from_bytes(challenge[8:], "big") ^ counter).to_bytes(4, "big")

def seal(key: bytes, challenge: bytes, sequence: int, payload: bytes, response=False) -> bytes:
    if not payload or len(payload) > MAX_PAYLOAD:
        raise ValueError("LAN payload exceeds its limit")
    aad = b"FAP-LAN-1:S" if response else b"FAP-LAN-1:C"
    encrypted = AESGCM(key).encrypt(nonce_for(challenge, sequence, response), payload, aad)
    return f"{sequence:08x}:".encode() + encrypted.hex().encode() + b"\n"

def unseal(key: bytes, challenge: bytes, sequence: int, frame: bytes, response=False) -> bytes:
    if len(frame) > 9 + 2*(MAX_PAYLOAD+16)+1 or not frame.endswith(b"\n"):
        raise ValueError("Invalid LAN frame length")
    prefix, encoded = frame[:-1].split(b":", 1)
    if prefix != f"{sequence:08x}".encode() or len(encoded) < 34:
        raise ValueError("Unexpected LAN sequence")
    aad = b"FAP-LAN-1:S" if response else b"FAP-LAN-1:C"
    return AESGCM(key).decrypt(nonce_for(challenge, sequence, response), bytes.fromhex(encoded.decode()), aad)

class LanClient:
    def __init__(self, host: str, key: bytes, port=PORT):
        if len(key) != 32:
            raise ValueError("LAN key must contain 32 bytes")
        self.host, self.key, self.port = host, key, port
        self.writer = None
        self.is_connected = False
        self.sequence = 0

    async def __aenter__(self):
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, limit=8192), 10)
            client_nonce = secrets.token_bytes(12)
            self.writer.write(json.dumps({'v':1, 'client_nonce':client_nonce.hex()}).encode()+b'\n')
            await asyncio.wait_for(self.writer.drain(), 5)
            hello = await asyncio.wait_for(self.reader.readline(), 5)
            if len(hello) > 192:
                raise ValueError("Oversized LAN greeting")
            value = json.loads(hello)
            if value.get("v") != 1:
                raise ValueError("Unsupported LAN protocol")
            server_nonce = bytes.fromhex(value["nonce"])
            expected = handshake_digest(self.key, client_nonce, server_nonce)
            if not hmac.compare_digest(bytes.fromhex(value.get('auth', '')), expected):
                raise ValueError("LAN device authentication failed; check the pairing key")
            self.challenge = handshake_digest(self.key, client_nonce, server_nonce, b'N')[:12]
            self.is_connected = True
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def send_payload(self, payload: bytes):
        self.sequence += 1
        try:
            self.writer.write(seal(self.key, self.challenge, self.sequence, payload))
            await asyncio.wait_for(self.writer.drain(), 5)
            frame = await asyncio.wait_for(self.reader.readline(), 5)
            response = json.loads(unseal(self.key, self.challenge, self.sequence, frame, True))
            if response != {"ok": True}:
                raise ValueError("Device rejected LAN payload")
        except BaseException:
            self.is_connected = False
            raise

    async def __aexit__(self, *_):
        self.is_connected = False
        if self.writer:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError):
                pass

def load_key(path: str) -> bytes:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    key = bytes.fromhex(data["key"])
    if len(key) != 32:
        raise ValueError("Invalid key in LAN configuration")
    return key
