"""The MQTT 3.1.1 subset EcoFlow's clients use (OASIS MQTT 3.1.1, sections 2-3).

Deliberately small: CONNECT/CONNACK, SUBSCRIBE/SUBACK, UNSUBSCRIBE/UNSUBACK,
PUBLISH QoS 0/1 + PUBACK, PINGREQ/PINGRESP, DISCONNECT.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

CONNECT, CONNACK, PUBLISH, PUBACK = 1, 2, 3, 4
SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK = 8, 9, 10, 11
PINGREQ, PINGRESP, DISCONNECT = 12, 13, 14

CONNACK_ACCEPTED = 0
CONNACK_BAD_PROTOCOL = 1
CONNACK_BAD_CREDENTIALS = 4  # paho reports 134
CONNACK_NOT_AUTHORIZED = 5  # paho reports 135, as EcoFlow's broker does

MAX_PACKET = 1 << 20


class ProtocolError(Exception):
    """A malformed or unsupported packet: the broker drops that connection."""


@dataclass(frozen=True)
class Packet:
    type: int
    flags: int
    body: bytes


async def read_packet(reader: asyncio.StreamReader) -> Packet:
    first = (await reader.readexactly(1))[0]
    length = 0
    for shift in (0, 7, 14, 21):
        byte = (await reader.readexactly(1))[0]
        length |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
    else:
        raise ProtocolError("remaining length longer than 4 bytes")
    if length > MAX_PACKET:
        raise ProtocolError(f"packet of {length} bytes exceeds the limit")
    return Packet(first >> 4, first & 0x0F, await reader.readexactly(length))


def encode(packet_type: int, flags: int, body: bytes) -> bytes:
    out = bytearray([(packet_type << 4) | flags])
    n = len(body)
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | 0x80 if n else byte)
        if not n:
            return bytes(out) + body


def _str(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("!H", len(raw)) + raw


class _Cursor:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def take(self, n: int) -> bytes:
        if self._pos + n > len(self._data):
            raise ProtocolError("packet truncated")
        chunk = self._data[self._pos : self._pos + n]
        self._pos += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int(struct.unpack("!H", self.take(2))[0])

    def binary(self) -> bytes:
        return self.take(self.u16())

    def string(self) -> str:
        try:
            return self.binary().decode()
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid UTF-8 string") from exc

    def rest(self) -> bytes:
        return self.take(len(self._data) - self._pos)

    @property
    def done(self) -> bool:
        return self._pos >= len(self._data)


@dataclass(frozen=True)
class Connect:
    client_id: str
    username: str | None
    password: str | None
    keepalive: int
    protocol_level: int


def parse_connect(body: bytes) -> Connect:
    c = _Cursor(body)
    name = c.string()
    level = c.u8() if name == "MQTT" else -1
    if name != "MQTT":
        c.u8()
    flags = c.u8()
    keepalive = c.u16()
    client_id = c.string()
    if flags & 0x04:  # will topic + will message
        c.string()
        c.binary()
    username = c.string() if flags & 0x80 else None
    password = c.binary().decode(errors="replace") if flags & 0x40 else None
    return Connect(client_id, username, password, keepalive, level)


def connack(return_code: int) -> bytes:
    return encode(CONNACK, 0, bytes([0, return_code]))


@dataclass(frozen=True)
class Publish:
    topic: str
    payload: bytes
    qos: int
    packet_id: int | None


def parse_publish(flags: int, body: bytes) -> Publish:
    qos = (flags >> 1) & 0x03
    if qos > 1:
        raise ProtocolError(f"QoS {qos} is not supported")
    c = _Cursor(body)
    topic = c.string()
    packet_id = c.u16() if qos else None
    return Publish(topic, c.rest(), qos, packet_id)


def publish(topic: str, payload: bytes) -> bytes:
    """A QoS 0 PUBLISH. The twin delivers at QoS 0 (legal for any granted QoS)."""
    return encode(PUBLISH, 0, _str(topic) + payload)


def puback(packet_id: int) -> bytes:
    return encode(PUBACK, 0, struct.pack("!H", packet_id))


def parse_subscribe(body: bytes) -> tuple[int, list[tuple[str, int]]]:
    c = _Cursor(body)
    packet_id = c.u16()
    subs: list[tuple[str, int]] = []
    while not c.done:
        topic = c.string()
        subs.append((topic, c.u8() & 0x03))
    if not subs:
        raise ProtocolError("SUBSCRIBE without topics")
    return packet_id, subs


def suback(packet_id: int, granted: list[int]) -> bytes:
    return encode(SUBACK, 0, struct.pack("!H", packet_id) + bytes(granted))


def parse_unsubscribe(body: bytes) -> tuple[int, list[str]]:
    c = _Cursor(body)
    packet_id = c.u16()
    topics: list[str] = []
    while not c.done:
        topics.append(c.string())
    return packet_id, topics


def unsuback(packet_id: int) -> bytes:
    return encode(UNSUBACK, 0, struct.pack("!H", packet_id))


PINGRESP_PACKET = encode(PINGRESP, 0, b"")


def topic_matches(filter_: str, topic: str) -> bool:
    """MQTT wildcards: ``+`` matches one level, a final ``#`` the rest."""
    f_parts, t_parts = filter_.split("/"), topic.split("/")
    for i, part in enumerate(f_parts):
        if part == "#":
            return True
        if i >= len(t_parts) or (part not in ("+", t_parts[i])):
            return False
    return len(f_parts) == len(t_parts)
