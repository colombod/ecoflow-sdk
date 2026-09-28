"""The SDK, unmodified except for Endpoints, against the twin over real TLS."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ecoflow.client import EcoFlowClient
from ecoflow_twin.recording import Recording
from ecoflow_twin.server import (
    TWIN_ACCESS_KEY,
    TWIN_SECRET_KEY,
    TwinEndpoints,
    TwinServer,
)
from tests.support.recordings import RECORDINGS_DIR

SYN = Recording.load(RECORDINGS_DIR / "synthetic" / "recording.json")


def _client(endpoints: TwinEndpoints) -> EcoFlowClient:
    return EcoFlowClient(
        TWIN_ACCESS_KEY, TWIN_SECRET_KEY, endpoints=endpoints.sdk_endpoints()
    )


async def test_sdk_discovers_and_streams_over_tls(tmp_path: Path) -> None:
    async with TwinServer(SYN, state_dir=tmp_path, speed=20) as endpoints:
        client = _client(endpoints)
        await client.connect()
        try:
            assert client.mqtt_connected
            assert {d.sn for d in client.stream_units + client.plugs} <= set(
                SYN.serials
            )
            async with asyncio.timeout(5):
                event = await anext(client.events())
            assert event["data"] is not None
        finally:
            await client.disconnect()


async def test_sdk_relay_command_changes_twin_state(tmp_path: Path) -> None:
    async with TwinServer(SYN, state_dir=tmp_path, speed=20) as endpoints:
        client = _client(endpoints)
        await client.connect()
        try:
            stream = client.stream_units[0]
            await stream.set_relay3(on=True)
            await asyncio.sleep(0.3)
            assert (await stream.refresh()).relay3_on is True
        finally:
            await client.disconnect()


async def test_second_sdk_session_is_refused_like_ecoflow(tmp_path: Path) -> None:
    async with TwinServer(SYN, state_dir=tmp_path) as endpoints:
        first, second = _client(endpoints), _client(endpoints)
        await first.connect()
        try:
            await second.connect()  # SDK logs and degrades to REST-only on 135
            assert first.mqtt_connected and not second.mqtt_connected
        finally:
            await second.disconnect()
            await first.disconnect()


def test_env_points_any_app_at_the_twin() -> None:
    from ecoflow_twin.server import TwinEndpoints

    e = TwinEndpoints(
        "https://127.0.0.1:1", "127.0.0.1", 2, "/ca.pem", "a", "s", "open-twin", "p"
    )
    assert e.env() == {
        "ECOFLOW_REST_BASE": "https://127.0.0.1:1",
        "ECOFLOW_CA_FILE": "/ca.pem",
        "ECOFLOW_ACCESS_KEY": "a",
        "ECOFLOW_SECRET_KEY": "s",
    }


def _read(path: str) -> bytes:
    return Path(path).read_bytes()


async def test_restart_reuses_state_dir(tmp_path: Path) -> None:
    """Apps keep trusting the same ca.pem across twin restarts."""
    async with TwinServer(SYN, state_dir=tmp_path) as first:
        ca = _read(first.ca_file)
    async with TwinServer(SYN, state_dir=tmp_path) as second:
        assert _read(second.ca_file) == ca
