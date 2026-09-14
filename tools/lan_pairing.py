"""LAN discovery hints and bounded, human-verified pairing. No key in discovery."""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DISCOVERY_PORT = 8764
DOMAIN = b'FAP-PAIR-1:'


def parse_discovery(payload, address, nonce):
    if len(payload) > 256 or not ipaddress.IPv4Address(address).is_private:
        raise ValueError('Invalid discovery reply')
    value = json.loads(payload)
    if (not isinstance(value, dict) or value.get('app') != 'passport' or value.get('v') != 1 or value.get('nonce') != nonce
            or not re.fullmatch('[0-9a-f]{12}', value.get('id', ''))
            or value.get('port') != 8765 or type(value.get('pair')) is not bool):
        raise ValueError('Invalid discovery reply')
    return dict(id=value['id'], host=address, port=8765,
                name='Passport-' + value['id'][-6:].upper(), available=value['pair'])


async def discover(timeout=2.5, host=None):
    if host is not None:
        try:
            address = ipaddress.IPv4Address(host)
        except (ValueError, TypeError):
            raise ValueError("请输入有效的局域网 IPv4 地址") from None
        if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError("请输入有效的局域网 IPv4 地址")
        host = str(address)
    nonce = secrets.token_hex(8)
    request = ('FAP_DISCOVER1 ' + nonce).encode()
    destinations = {'255.255.255.255'}
    # Directed broadcasts also work when Windows picks a VPN as its default route.
    import psutil
    for addresses in psutil.net_if_addrs().values():
        for address in addresses:
            if address.family == socket.AF_INET and address.netmask:
                network = ipaddress.IPv4Network(f'{address.address}/{address.netmask}', strict=False)
                if not network.is_loopback and ipaddress.IPv4Address(address.address).is_private:
                    destinations.add(str(network.broadcast_address))
    if host is not None:
        destinations = {host}
    loop = asyncio.get_running_loop()
    result = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('0.0.0.0', 0))
        sock.setblocking(False)
        for address in sorted(destinations)[:16]:
            try:
                await loop.sock_sendto(sock, request, (address, DISCOVERY_PORT))
            except OSError:
                continue
        deadline = loop.time() + timeout
        count = 0
        while loop.time() < deadline and count < 128 and len(result) < 16:
            try:
                payload, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, 257), deadline - loop.time())
                count += 1
                if peer[1] != DISCOVERY_PORT or (host is not None and peer[0] != host):
                    continue
                item = parse_discovery(payload, peer[0], nonce)
                result[(item['id'], item['host'])] = item
            except (ValueError, KeyError, TypeError):
                continue
            except asyncio.TimeoutError:
                break
    return list(result.values())


def derive(shared, client_pub, server_pub, client_nonce, server_nonce, identity):
    transcript = DOMAIN + client_pub + server_pub + client_nonce + server_nonce + identity.encode('ascii')
    digest = hashlib.sha256(transcript).digest()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=digest, info=DOMAIN+b'key').derive(shared)
    code = int.from_bytes(hmac.new(key, DOMAIN+b'sas', hashlib.sha256).digest()[:4], 'big') % 1000000
    return key, digest, f'{code:06d}'


class Pairing:
    def __init__(self):
        self.writer = None
        self.key = None
        self.deadline = 0

    async def line(self, timeout=5):
        value = await asyncio.wait_for(self.reader.readline(), timeout)
        if not value.endswith(b'\n') or len(value) > 256:
            raise ValueError('配对响应无效，请重试')
        return value[:-1].decode('ascii')

    async def send(self, value):
        self.writer.write(value.encode('ascii') + b'\n')
        await asyncio.wait_for(self.writer.drain(), 3)

    async def start(self, device):
        self.device = device
        self.id = secrets.token_hex(16)  # Browser actions are bound to this session.
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(device['host'], device['port'], limit=257), 5)
            private = ec.generate_private_key(ec.SECP256R1())
            public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            nonce = secrets.token_bytes(16)
            # Commit before seeing the server ephemeral key: no adaptive SAS grinding.
            commit = hashlib.sha256(DOMAIN+b'commit'+public+nonce).hexdigest()
            await self.send('FAP_PAIR1 ' + commit)
            fields = (await self.line()).split(' ')
            if len(fields) != 4 or fields[0] != 'FAP_PAIR1' or fields[3] != device['id']:
                raise ValueError('设备不支持新配对或身份已变化，请更新固件后重新搜索')
            if not re.fullmatch('[0-9a-f]{130}', fields[1]) or not re.fullmatch('[0-9a-f]{32}', fields[2]):
                raise ValueError('配对响应无效')
            server_pub, server_nonce = bytes.fromhex(fields[1]), bytes.fromhex(fields[2])
            peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_pub)
            self.key, self.digest, self.code = derive(private.exchange(ec.ECDH(), peer), public,
                                                     server_pub, nonce, server_nonce, device['id'])
            await self.send('FAP_REVEAL1 ' + public.hex() + ' ' + nonce.hex())
            if await self.line() != 'FAP_READY1':
                raise ValueError('设备暂时无法配对，请稍后重试')
            self.deadline = asyncio.get_running_loop().time() + 30
            return dict(id=self.id, code=self.code, name=device['name'], seconds=30)
        except BaseException:
            await self.close()
            raise

    async def confirm(self, observed_id):
        remaining = self.deadline - asyncio.get_running_loop().time()
        if observed_id != self.id or remaining <= 0 or not self.key:
            raise ValueError('配对已过期，请重新搜索并连接')
        try:
            proof = hmac.new(self.key, DOMAIN+b'confirm', hashlib.sha256).hexdigest()
            await self.send('FAP_CONFIRM1 ' + proof)
            fields = (await self.line(min(remaining, 30))).split(' ')
            if asyncio.get_running_loop().time() >= self.deadline:
                raise ValueError('配对已过期，请重新开始')
            if len(fields) != 3 or fields[0] != 'FAP_KEY1' or not re.fullmatch('[0-9a-f]{24}', fields[1]) or not re.fullmatch('[0-9a-f]{96}', fields[2]):
                raise ValueError('设备未确认配对，请重试')
            key = AESGCM(self.key).decrypt(bytes.fromhex(fields[1]), bytes.fromhex(fields[2]), self.digest)
            if len(key) != 32:
                raise ValueError('配对响应无效')
            return dict(key=key.hex(), device_id=self.device['id'])
        finally:
            await self.close()

    async def close(self):
        self.key = None
        if self.writer:
            writer, self.writer = self.writer, None
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass
