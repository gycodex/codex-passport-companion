# LAN automatic pairing protocol (preview)

This preview removes file transfer from normal first-time setup. Wi-Fi provisioning
still uses the device hotspot. Then Passport.exe discovers a device on the local
network and asks the user to compare six digits on both screens and confirm on both
sides. Existing PSKs and the authenticated LAN transport remain compatible.

## Wire format and bounds

UDP 8764 receives `FAP_DISCOVER1 <16 lowercase hex nonce>` (30 bytes). Replies
contain app/version, the same nonce, a 12-hex Wi-Fi MAC identifier, TCP port 8765,
and pairing availability. Discovery carries no secret and is only an untrusted
address hint. Replies are limited to four per second. The desktop bounds reply
size, packet count, discovered device count, and duration.

TCP 8765 accepts these newline-terminated pairing lines before normal LAN auth:

1. Client: `FAP_PAIR1 <SHA256 commitment, 64 hex>`.
2. Device: `FAP_PAIR1 <uncompressed P256 public key, 130 hex> <nonce, 32 hex> <device id, 12 hex>`.
3. Client: `FAP_REVEAL1 <public key, 130 hex> <nonce, 32 hex>`.
4. Device: `FAP_READY1` after checking the commitment and creating a 30-second physical confirmation gate.
5. Client: `FAP_CONFIRM1 <confirmation HMAC, 64 hex>` only after the computer user confirms.
6. Device: `FAP_KEY1 <GCM nonce, 24 hex> <encrypted PSK and tag, 96 hex>` only after both confirmations.

All pairing lines fit within 256 bytes. Handshake phases have five-second read
deadlines; physical confirmation has a 30-second absolute deadline. Device attempts
are limited to one per minute, including failed attempts. A fresh rendered-view and
pairing-session generation must match before a button click can approve. Rejection,
expiry, disconnect, or conflicting sensitive UI aborts the pending exchange. A
physical approval is single-use; after approving on the device, cancellation can
still be performed on the computer until completion.

## Cryptographic construction

Let D be ASCII `FAP-PAIR-1:` (11 bytes), C and S the respective 65-byte public keys,
Nc and Ns the respective 16-byte random nonces, and I the 12-byte ASCII device id.

- Commitment: SHA256(D || `commit` || C || Nc), sent before the device's ephemeral public key.
- T: SHA256(D || C || S || Nc || Ns || I).
- K: HKDF-SHA256(P256 ECDH shared secret, salt=T, info=D || `key`, length=32).
- Display: the first four bytes of HMAC-SHA256(K, D || `sas`), big endian, modulo 1,000,000, padded to six digits.
- Client confirmation: HMAC-SHA256(K, D || `confirm`).
- PSK delivery: AES-256-GCM with K, random 12-byte nonce, 16-byte tag, and T as AAD.

The commitment prevents choosing an ephemeral key after learning the other party's
key to grind for matching short codes. This is a custom numeric-comparison protocol,
not an implementation of ZRTP or a security-certified pairing standard. Comparing
both screens is essential; ignoring the comparison defeats its authentication.
A six-digit comparison has limited guessing resistance, hence the attempt rate
limit. Network peers can still deny service; no Internet exposure is intended.

The desktop only persists the PSK after verified decryption and a still-current
session. API status never includes the key. Future rediscovery must complete the
existing PSK challenge authentication before a device is trusted. Device identity
is not a certificate. Existing paired computers retain access because the shared
PSK is not rotated by this flow. Device reset/USB reconfiguration remain the means
to replace it. Hardware RAM, entropy, button behavior, and long-duration operation
require physical acceptance testing in addition to host tests and compilation.

## 跨子网按 IP 查找

自动广播搜索不到设备时，在电脑端展开“跨子网 / 按 IP 查找”，填写设备无线网络页面的 IPv4 地址，点击“按 IP 查找并配对”。找到后仍需核对两端六位码并确认，不需要配对文件。要求电脑可访问设备的 UDP 8764 和 TCP 8765；这不会绕过路由器隔离。
