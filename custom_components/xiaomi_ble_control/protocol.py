"""Authenticated Mi Standard BLE GATT transport for szxzh.fan.f11.

No mesh/gateway writes: use an active Home Assistant Bluetooth connection.
"""

import asyncio
import hmac
import os
import struct
from collections.abc import Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def uuid(value: int) -> str:
    return f"{value:08x}-0000-1000-8000-00805f9b34fb"


AUTH = uuid(0x19)
STATUS = uuid(0x10)
TX = uuid(0x1A)
RX = uuid(0x1B)
INFO = uuid(0x1C)
READY = bytes.fromhex("00000101")
OK = bytes.fromhex("00000100")
ACK = bytes.fromhex("00000300")


def set_property(tid: int, siid: int, piid: int, value: int) -> bytes:
    """Encode an unsigned F11 property in MI GATT Spec version 2."""
    width, fmt = (2, 3) if (siid, piid) == (3, 3) else (1, 1)
    prop = struct.pack("<BHH", siid, piid, fmt << 12 | width)
    payload = bytes((0, 1)) + prop + value.to_bytes(width, "little")
    return struct.pack("<HH", 0x2000 | (len(payload) + 4), tid) + payload


def decode_properties(packet: bytes) -> tuple[int, int, dict]:
    """Reject malformed packets before exposing values to entities."""
    if len(packet) < 6:
        raise ValueError("Truncated GATT spec packet")
    header, tid, op, count = struct.unpack_from("<HHBB", packet)
    if header >> 12 != 2 or header & 0xFFF != len(packet):
        raise ValueError("Invalid GATT spec header")
    values = {}
    offset = 6
    if op not in (1, 3, 4):
        return tid, op, values
    for _ in range(count):
        if offset + 5 > len(packet):
            raise ValueError("Truncated GATT property")
        siid, piid, kind = struct.unpack_from("<BHH", packet, offset)
        offset += 5
        if op == 1:
            values[siid, piid] = struct.unpack("<h", struct.pack("<H", kind))[0]
            continue
        length, fmt = kind & 0xFFF, kind >> 12
        if offset + length > len(packet):
            raise ValueError("Truncated GATT value")
        if fmt in (0, 1, 2, 3, 4, 5, 6, 7, 8):
            widths = (1, 1, 1, 2, 2, 4, 4, 8, 8)
            if length != widths[fmt]:
                raise ValueError("Invalid GATT value width")
            values[siid, piid] = int.from_bytes(
                packet[offset : offset + length], "little", signed=fmt in (2, 4, 6, 8)
            )
        offset += length
    if offset != len(packet):
        raise ValueError("Trailing GATT property bytes")
    return tid, op, values


def speed_percentage(raw: int) -> int:
    return max(0, min(100, raw - 128))


class AuthenticationError(ValueError):
    """The device did not authenticate the supplied Mi BLE token."""


class F11Session:
    """One connection/session. Never log credentials, keys or ciphertext."""

    def __init__(self, client, token: bytes, on_properties: Callable):
        if len(token) != 12:
            raise ValueError("F11 requires a 12-byte BLE token (24 hex characters)")
        self.client = client
        self._token = token
        self.on_properties = on_properties
        self._control = {AUTH: asyncio.Queue(), TX: asyncio.Queue()}
        self._received = asyncio.Queue()
        self._status = asyncio.Queue()
        self._notifications = asyncio.Queue()
        self._worker = None
        self._parts = {}
        self._send_lock = asyncio.Lock()
        self._pending = {}
        self._tid = 0
        self._counter = 0
        self._rx_counter = -1
        self._dev_ccm = self._app_ccm = None

    async def start(self):
        self._worker = asyncio.create_task(self._process_notifications())
        for char in (RX, TX, INFO, AUTH, STATUS):
            await self.client.start_notify(
                char, lambda _, data, char=char: self._notifications.put_nowait((char, bytes(data)))
            )
        nonce = os.urandom(16)
        await self.client.write_gatt_char(STATUS, bytes.fromhex("24000000"), response=False)
        await self._send(AUTH, 0x0B, nonce)
        kind, remote_nonce = await asyncio.wait_for(self._received.get(), 10)
        if kind != 0x0D or len(remote_nonce) != 16:
            raise AuthenticationError("Invalid Mi authentication nonce")
        keys = HKDF(
            algorithm=hashes.SHA256(),
            length=64,
            salt=nonce + remote_nonce,
            info=b"mible-login-info",
        ).derive(self._token)
        kind, proof = await asyncio.wait_for(self._received.get(), 10)
        expected = hmac.digest(keys[:16], remote_nonce + nonce, "sha256")
        if kind != 0x0C or not hmac.compare_digest(proof, expected):
            raise AuthenticationError("Mi authentication proof failed")
        self._dev_ccm = AESCCM(keys[:16], tag_length=4)
        self._app_ccm = AESCCM(keys[16:32], tag_length=4)
        self._dev_iv, self._app_iv = keys[32:36], keys[36:40]
        await self._send(AUTH, 0x0A, hmac.digest(keys[16:32], nonce + remote_nonce, "sha256"))
        status = await asyncio.wait_for(self._status.get(), 10)
        if status != bytes.fromhex("21000000"):
            raise AuthenticationError("Mi login rejected")

    @property
    def worker_done(self):
        return self._worker is not None and self._worker.done()

    def raise_worker_error(self):
        if self.worker_done:
            self._worker.result()

    async def close(self):
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("F11 disconnected"))
        self._dev_ccm = self._app_ccm = None

    async def _send(self, char: str, kind: int, payload: bytes):
        # Use mandatory BLE ATT MTU 23: avoids proxy-specific MTU negotiation.
        count = (len(payload) + 17) // 18
        await self.client.write_gatt_char(
            char, struct.pack("<HBBH", 0, 0, kind, count), response=False
        )
        if await asyncio.wait_for(self._control[char].get(), 10) != READY:
            raise ConnectionError("Mi transport not ready")
        for i in range(count):
            await self.client.write_gatt_char(
                char, struct.pack("<H", i + 1) + payload[i * 18 : (i + 1) * 18], response=False
            )
        if await asyncio.wait_for(self._control[char].get(), 10) != OK:
            raise ConnectionError("Mi transport transfer rejected")

    async def _process_notifications(self):
        while True:
            char, data = await self._notifications.get()
            if char == STATUS:
                self._status.put_nowait(data)
                continue
            if char == INFO:
                continue
            if len(data) < 2:
                continue
            frame = int.from_bytes(data[:2], "little")
            if frame == 0:
                if len(data) < 4:
                    continue
                mode, kind = data[2:4]
                if mode == 1:
                    if char in self._control:
                        self._control[char].put_nowait(data)
                    continue
                if mode == 2:
                    await self.client.write_gatt_char(char, ACK, response=False)
                    self._receive(char, kind, data[4:])
                elif mode == 0 and len(data) == 6:
                    count = int.from_bytes(data[4:6], "little")
                    if not 0 < count <= 256:
                        continue
                    self._parts[char] = (kind, count, bytearray(), 1)
                    await self.client.write_gatt_char(char, READY, response=False)
            elif char in self._parts:
                kind, count, payload, expected = self._parts[char]
                if frame != expected:
                    raise ValueError("Out-of-order Mi transport frame")
                payload.extend(data[2:])
                if frame == count:
                    del self._parts[char]
                    await self.client.write_gatt_char(char, OK, response=False)
                    self._receive(char, kind, bytes(payload))
                else:
                    self._parts[char] = (kind, count, payload, expected + 1)

    def _receive(self, char: str, kind: int, data: bytes):
        if char == AUTH:
            self._received.put_nowait((kind, data))
            return
        if char != RX or kind != 0 or self._dev_ccm is None or len(data) < 6:
            return
        counter = int.from_bytes(data[:2], "little")
        if counter <= self._rx_counter:
            return  # replay/duplicate, counters must not wrap within a session
        nonce = self._dev_iv + bytes(4) + struct.pack("<I", counter)
        packet = self._dev_ccm.decrypt(nonce, data[2:], None)
        self._rx_counter = counter
        tid, op, values = decode_properties(packet)
        if op in (3, 4):
            self.on_properties(values)
        elif op == 1 and (future := self._pending.get(tid)) and not future.done():
            future.set_result(values)

    async def write(self, siid: int, piid: int, value: int):
        async with self._send_lock:
            if self._app_ccm is None or self._counter >= 65535:
                raise ConnectionError("F11 requires reconnection")
            self._tid = (self._tid + 1) & 0xFFFF
            self._counter += 1
            packet = set_property(self._tid, siid, piid, value)
            nonce = self._app_iv + bytes(4) + struct.pack("<I", self._counter)
            data = struct.pack("<H", self._counter) + self._app_ccm.encrypt(nonce, packet, None)
            future = asyncio.get_running_loop().create_future()
            self._pending[self._tid] = future
            try:
                await self._send(TX, 0, data)
                result = await asyncio.wait_for(future, 10)
                if result.get((siid, piid)) != 0:
                    raise ValueError("F11 property write rejected")
            finally:
                self._pending.pop(self._tid, None)
