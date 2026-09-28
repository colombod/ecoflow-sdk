from __future__ import annotations

import asyncio
import struct

import pytest

from ecoflow_twin import mqtt_codec as mc


def _s(v: str) -> bytes:
    return struct.pack("!H", len(v)) + v.encode()


async def _read(data: bytes) -> mc.Packet:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return await mc.read_packet(reader)


@pytest.mark.parametrize(
    "size", [0, 127, 128, 16383, 16384, 1_000_000]
)  # 1-3 byte lengths
async def test_remaining_length_roundtrip(size: int) -> None:
    packet = await _read(mc.encode(mc.PUBLISH, 0, b"x" * size))
    assert packet.type == mc.PUBLISH and len(packet.body) == size


async def test_oversized_packet_rejected() -> None:
    with pytest.raises(mc.ProtocolError):
        await _read(bytes([0x30, 0xFF, 0xFF, 0xFF, 0x7F]))


def test_parse_connect_with_credentials() -> None:
    body = (
        _s("MQTT")
        + bytes([4, 0xC2])
        + struct.pack("!H", 60)
        + _s("cid")
        + _s("user")
        + _s("pass")
    )
    c = mc.parse_connect(body)
    assert (c.client_id, c.username, c.password, c.keepalive, c.protocol_level) == (
        "cid",
        "user",
        "pass",
        60,
        4,
    )


def test_parse_connect_skips_will() -> None:
    body = (
        _s("MQTT")
        + bytes([4, 0x06])
        + struct.pack("!H", 30)
        + _s("cid")
        + _s("will/t")
        + _s("bye")
    )
    assert mc.parse_connect(body).username is None


def test_parse_connect_mqtt31_reports_unsupported() -> None:
    body = _s("MQIsdp") + bytes([3, 0x02]) + struct.pack("!H", 30) + _s("cid")
    assert mc.parse_connect(body).protocol_level != 4


def test_truncated_connect_is_protocol_error() -> None:
    with pytest.raises(mc.ProtocolError):
        mc.parse_connect(_s("MQTT") + bytes([4]))


def test_publish_qos1_roundtrip() -> None:
    body = _s("/a/b") + struct.pack("!H", 7) + b'{"x":1}'
    p = mc.parse_publish(0x02, body)
    assert (p.topic, p.qos, p.packet_id, p.payload) == ("/a/b", 1, 7, b'{"x":1}')


def test_publish_qos2_unsupported() -> None:
    with pytest.raises(mc.ProtocolError):
        mc.parse_publish(0x04, _s("/a") + b"\x00\x01")


def test_subscribe_and_suback() -> None:
    pid, subs = mc.parse_subscribe(
        struct.pack("!H", 3) + _s("/a/+") + b"\x01" + _s("/b/#") + b"\x00"
    )
    assert pid == 3 and subs == [("/a/+", 1), ("/b/#", 0)]
    assert mc.suback(3, [1, 0]) == bytes([0x90, 4, 0, 3, 1, 0])


def test_fixed_packets() -> None:
    assert mc.connack(5) == bytes([0x20, 2, 0, 5])
    assert mc.puback(9) == bytes([0x40, 2, 0, 9])
    assert mc.PINGRESP_PACKET == bytes([0xD0, 0])


@pytest.mark.parametrize(
    ("filter_", "topic", "match"),
    [
        ("/open/a/SN/quota", "/open/a/SN/quota", True),
        ("/open/a/+/quota", "/open/a/SN/quota", True),
        ("/open/a/#", "/open/a/SN/quota", True),
        ("/open/a/+/quota", "/open/a/SN/set", False),
        ("/open/a/SN", "/open/a/SN/quota", False),
    ],
)
def test_topic_matches(filter_: str, topic: str, match: bool) -> None:
    assert mc.topic_matches(filter_, topic) is match
