from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import aiomqtt
import pytest
import pytest_asyncio

from ecoflow_twin.broker import Broker, BrokerConfig
from ecoflow_twin.recording import Recording
from ecoflow_twin.state import DeviceState
from tests.support.recordings import RECORDINGS_DIR

SYN = Recording.load(RECORDINGS_DIR / "synthetic" / "recording.json")
BK = next(s for s in SYN.serials if s.startswith("BK11"))
HW = next(s for s in SYN.serials if s.startswith("HW52"))
ACCOUNT, PASSWORD = "open-twin", "pw"


@pytest_asyncio.fixture
async def broker() -> AsyncIterator[tuple[Broker, int]]:
    b = Broker(
        SYN,
        DeviceState(SYN),
        BrokerConfig(ACCOUNT, PASSWORD, speed=50, client_id_limit=3),
    )
    server = await asyncio.start_server(b.handle, "127.0.0.1", 0)
    yield b, server.sockets[0].getsockname()[1]
    b.close_all()
    server.close()
    await server.wait_closed()


def _client(
    port: int, identifier: str = "cid-1", password: str = PASSWORD
) -> aiomqtt.Client:
    return aiomqtt.Client(
        hostname="127.0.0.1",
        port=port,
        username=ACCOUNT,
        password=password,
        identifier=identifier,
    )


async def _next(client: aiomqtt.Client) -> aiomqtt.Message:
    async with asyncio.timeout(3):
        return await anext(aiter(client.messages))


async def test_plays_timeline_to_subscribed_topics_only(broker: Any) -> None:
    _b, port = broker
    async with _client(port) as c:
        await c.subscribe(f"/open/{ACCOUNT}/{BK}/quota", qos=1)
        topics = {str((await _next(c)).topic) for _ in range(4)}
    assert topics == {f"/open/{ACCOUNT}/{BK}/quota"}


async def test_wildcard_subscription(broker: Any) -> None:
    _b, port = broker
    async with _client(port) as c:
        await c.subscribe(f"/open/{ACCOUNT}/+/quota")
        seen = {str((await _next(c)).topic).split("/")[3] for _ in range(6)}
    assert seen == {BK, HW}


async def test_bad_password_is_134(broker: Any) -> None:
    _b, port = broker
    with pytest.raises(aiomqtt.MqttCodeError) as err:
        async with _client(port, password="nope"):
            pass
    assert err.value.rc == 134


async def test_second_session_for_account_is_135(broker: Any) -> None:
    """Quirk 2: the broker allows ONE session per account."""
    b, port = broker
    async with _client(port, "cid-1"):
        with pytest.raises(aiomqtt.MqttCodeError) as err:
            async with _client(port, "cid-1"):
                pass
        assert err.value.rc == 135
    await asyncio.sleep(0.1)
    async with _client(port, "cid-1"):  # free again once the first disconnected
        pass
    assert "account already has a session (Quirk 2)" in b.stats.refused


async def test_client_id_quota_is_135(broker: Any) -> None:
    """Quirk 1: only N unique client IDs per account (limit 3 here)."""
    _b, port = broker
    for i in range(3):
        async with _client(port, f"cid-{i}"):
            pass
        await asyncio.sleep(0.05)
    with pytest.raises(aiomqtt.MqttCodeError) as err:
        async with _client(port, "cid-new"):
            pass
    assert err.value.rc == 135
    async with _client(port, "cid-0"):  # a known ID still connects
        pass


async def test_set_command_replies_and_pushes(broker: Any) -> None:
    b, port = broker
    command = {
        "from": "ecoflow-python",
        "id": "42",
        "version": "1.0",
        "sn": BK,
        "cmdId": 17,
        "cmdFunc": 254,
        "dirDest": 1,
        "dirSrc": 1,
        "dest": 2,
        "needAck": True,
        "params": {"cfgRelay3Onoff": True},
    }
    async with _client(port) as c:
        await c.subscribe(f"/open/{ACCOUNT}/{BK}/set_reply")
        await c.publish(f"/open/{ACCOUNT}/{BK}/set", json.dumps(command), qos=1)
        reply = json.loads((await _next(c)).payload)  # type: ignore[arg-type]
    assert reply["id"] == "42" and str(reply["code"]) == "0"
    assert b.stats.connects == 1


async def test_ping_keeps_session(broker: Any) -> None:
    _b, port = broker
    client = aiomqtt.Client(
        hostname="127.0.0.1",
        port=port,
        username=ACCOUNT,
        password=PASSWORD,
        identifier="cid-ka",
        keepalive=1,
    )
    async with client:
        await asyncio.sleep(2.5)  # paho sends PINGREQ; a dead broker would drop us
        await client.subscribe(f"/open/{ACCOUNT}/{BK}/quota")
        await _next(client)


async def test_garbage_drops_only_that_connection(broker: Any) -> None:
    _b, port = broker
    _r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(b"\xff\xff\xff\xff\xff")
    await w.drain()
    w.close()
    async with _client(port):  # broker still serves others
        pass


async def test_empty_client_id_is_135(broker: Any) -> None:
    """Quirk 3: EcoFlow refuses an empty client ID with 135."""
    _b, port = broker
    with pytest.raises(aiomqtt.MqttCodeError) as err:
        async with _client(port, identifier=""):
            pass
    assert err.value.rc == 135
