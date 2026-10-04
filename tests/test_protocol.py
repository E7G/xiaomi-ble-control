"""Hardware-free F11 framing, authentication and property regression tests."""

import asyncio
import hmac
import importlib.util
import struct
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# The transport intentionally has no HA imports. Test it without HA installed.
spec = importlib.util.spec_from_file_location(
    "f11", Path(__file__).parents[1] / "custom_components/xiaomi_ble_control/protocol.py"
)
f11 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f11)

REPORT = bytes.fromhex(
    "32205300040703010001100203020001100103030002300000"
    "03040002300000030500011000030600011007020a04011001"
)


def test_property_codec():
    tid, op, props = f11.decode_properties(REPORT)
    assert (tid, op) == (83, 4)
    assert props == {(3, 1): 2, (3, 2): 1, (3, 3): 0, (3, 4): 0, (3, 5): 0, (3, 6): 7, (2, 1034): 1}
    assert f11.set_property(4, 3, 2, 20).hex() == "0c2004000001030200011014"
    assert f11.set_property(5, 3, 3, 480).hex() == "0d20050000010303000230e001"
    assert [f11.speed_percentage(n) for n in (0, 1, 128, 129, 148, 168, 228, 255)] == [
        0,
        0,
        0,
        1,
        20,
        40,
        100,
        100,
    ]


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        REPORT[:-1],
        b"\x32\x30" + REPORT[2:],
        REPORT[:6] + bytes.fromhex("03010002100200") + REPORT[12:],
    ],
)
def test_malformed_packets(packet):
    with pytest.raises(ValueError):
        f11.decode_properties(packet)


class FakeDevice:
    def __init__(self, bad_proof=False):
        self.callbacks = {}
        self.parts = {}
        self.token = bytes(range(12))
        self.remote_nonce = bytes(range(16))
        self.bad_proof = bad_proof
        self.seq = 0
        self.commands = []

    async def start_notify(self, char, callback):
        self.callbacks[char] = callback

    def notify(self, char, data):
        self.callbacks[char](char, data)

    async def write_gatt_char(self, char, data, response=False):
        assert response is False  # F11 authentication status is write-command only
        if char == f11.STATUS:
            assert data == bytes.fromhex("24000000")
            return
        frame = int.from_bytes(data[:2], "little")
        if frame == 0:
            if data[2] == 0:
                self.parts[char] = [data[3], int.from_bytes(data[4:6], "little"), bytearray()]
                self.notify(char, f11.READY)
            return
        kind, count, payload = self.parts[char]
        payload.extend(data[2:])
        if frame != count:
            return
        self.notify(char, f11.OK)
        if char == f11.AUTH and kind == 0x0B:
            self.app_nonce = bytes(payload)
            self.keys = HKDF(
                algorithm=hashes.SHA256(),
                length=64,
                salt=self.app_nonce + self.remote_nonce,
                info=b"mible-login-info",
            ).derive(self.token)
            proof = hmac.digest(self.keys[:16], self.remote_nonce + self.app_nonce, "sha256")
            if self.bad_proof:
                proof = bytes(32)
            self.notify(f11.AUTH, bytes.fromhex("0000020d") + self.remote_nonce)
            self.notify(f11.AUTH, bytes.fromhex("0000020c") + proof)
        elif char == f11.AUTH:
            assert bytes(payload) == hmac.digest(
                self.keys[16:32], self.app_nonce + self.remote_nonce, "sha256"
            )
            assert count == 2  # no MTU negotiation needed
            self.notify(f11.STATUS, bytes.fromhex("21000000"))
        elif char == f11.TX:
            counter = int.from_bytes(payload[:2], "little")
            nonce = self.keys[36:40] + bytes(4) + struct.pack("<I", counter)
            packet = AESCCM(self.keys[16:32], tag_length=4).decrypt(nonce, bytes(payload[2:]), None)
            self.commands.append(packet)
            tid = int.from_bytes(packet[2:4], "little")
            response = struct.pack("<HHBB", 0x200B, tid, 1, 1) + bytes.fromhex("0302000000")
            self.report(response)

    def report(self, packet, single=True, tamper=False):
        self.seq += 1
        nonce = self.keys[32:36] + bytes(4) + struct.pack("<I", self.seq)
        data = struct.pack("<H", self.seq) + AESCCM(self.keys[:16], tag_length=4).encrypt(
            nonce, packet, None
        )
        if tamper:
            data = data[:-1] + bytes([data[-1] ^ 1])
        if single:
            self.notify(f11.RX, bytes.fromhex("00000200") + data)
        else:
            count = (len(data) + 17) // 18
            self.notify(f11.RX, struct.pack("<HBBH", 0, 0, 0, count))
            for i in range(count):
                self.notify(f11.RX, struct.pack("<H", i + 1) + data[i * 18 : (i + 1) * 18])


@pytest.mark.asyncio
async def test_login_report_and_serialized_writes():
    device = FakeDevice()
    reports = []
    session = f11.F11Session(device, device.token, reports.append)
    try:
        await session.start()
        device.report(REPORT, single=False)
        await asyncio.sleep(0)
        assert reports[0][3, 2] == 1
        # A uint16 report occupies 19 encrypted bytes: final numbered frame
        # contains just one payload byte (three bytes including frame number).
        timer = bytearray(f11.set_property(1, 3, 3, 480))
        timer[4] = 4
        device.report(bytes(timer), single=False)
        await asyncio.sleep(0)
        assert reports[-1][3, 3] == 480
        await asyncio.gather(session.write(3, 2, 20), session.write(3, 2, 40))
        assert [packet[-1] for packet in device.commands] == [20, 40]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_reject_authentication_proof():
    device = FakeDevice(bad_proof=True)
    session = f11.F11Session(device, device.token, lambda _: None)
    try:
        with pytest.raises(ValueError, match="proof failed"):
            await session.start()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_reject_tampered_report():
    device = FakeDevice()
    reports = []
    session = f11.F11Session(device, device.token, reports.append)
    try:
        await session.start()
        device.report(REPORT, tamper=True)
        await asyncio.sleep(0)
        assert session._worker.done()
        assert not reports
    finally:
        await session.close()
