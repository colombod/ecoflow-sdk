"""Shared fixtures for live E2E tests.

Credentials come from tests/.env (gitignored) or the shell. Nothing here runs
unless pytest is invoked with ``--live`` (see tests/conftest.py).

Each fixture opens ONE client per test module. The MQTT fixture holds the
account's single broker session for the module's duration; stop any other
integration using the same keys (e.g. Home Assistant) first — AGENTS.md
Quirk 2 — or it will be disconnected, or this run will fail with error 135.

With ``--live=replay`` the same modules run against the **service twin**
(``ecoflow_twin``): real HTTPS + MQTT/TLS on local ports, serving each
recording in tests/recordings/. No network, no secrets.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio

from ecoflow.client import EcoFlowClient
from ecoflow.endpoints import Endpoints
from ecoflow_twin import (
    TWIN_ACCESS_KEY,
    TWIN_SECRET_KEY,
    Recording,
    TwinEndpoints,
    TwinServer,
)
from tests.support.recordings import all_recordings


@dataclass(frozen=True)
class PublicCreds:
    access_key: str
    secret_key: str
    region: str
    endpoints: Endpoints | None = None

    def client(self, *, enable_mqtt: bool) -> EcoFlowClient:
        return EcoFlowClient(
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            enable_mqtt=enable_mqtt,
            endpoints=self.endpoints or Endpoints(),
        )


@dataclass(frozen=True)
class MqttTiming:
    """How long to wait for pushes: real devices vs a time-compressed replay."""

    first_push_timeout_s: float
    settle_s: float


def replay_speed(recording: Recording) -> float:
    """Compress any recording so one loop of its timeline takes about 5 s."""
    return max(20.0, recording.duration_s / 5)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "replay" not in metafunc.fixturenames:
        return
    if metafunc.config.getoption("--live", default="off") == "replay":
        recordings = all_recordings()
        metafunc.parametrize(
            "replay",
            recordings,
            ids=[r.name for r in recordings],
            indirect=True,
            scope="module",
        )
    else:
        metafunc.parametrize(
            "replay", [None], ids=["live"], indirect=True, scope="module"
        )


@pytest.fixture(scope="module")
def replay(request: pytest.FixtureRequest) -> Recording | None:
    """The recording this module replays, or None when talking to the cloud."""
    return request.param


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def twin(
    replay: Recording | None, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[TwinEndpoints | None]:
    if replay is None:
        yield None
        return
    server = TwinServer(
        replay, state_dir=tmp_path_factory.mktemp("twin"), speed=replay_speed(replay)
    )
    async with server as endpoints:
        yield endpoints


@pytest.fixture(scope="module")
def public_creds(replay: Recording | None, twin: TwinEndpoints | None) -> PublicCreds:
    if replay is not None and twin is not None:
        region = str(replay.meta.get("region", "EU"))
        return PublicCreds(
            TWIN_ACCESS_KEY, TWIN_SECRET_KEY, region, twin.sdk_endpoints()
        )
    access_key = os.getenv("ECOFLOW_ACCESS_KEY", "")
    secret_key = os.getenv("ECOFLOW_SECRET_KEY", "")
    if not (access_key and secret_key):
        pytest.skip("ECOFLOW_ACCESS_KEY / ECOFLOW_SECRET_KEY not set (tests/.env)")
    return PublicCreds(access_key, secret_key, os.getenv("ECOFLOW_REGION", "EU"))


@pytest.fixture(scope="module")
def mqtt_timing(replay: Recording | None) -> MqttTiming:
    if replay is None:
        # Devices push every few seconds when online; the state dump comes in chunks.
        return MqttTiming(first_push_timeout_s=90, settle_s=5)
    loop_s = (replay.duration_s + 1) / replay_speed(replay)
    return MqttTiming(first_push_timeout_s=loop_s + 5, settle_s=loop_s + 0.2)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def rest_client(public_creds: PublicCreds) -> AsyncIterator[EcoFlowClient]:
    """Discovered client that never opens MQTT."""
    client = public_creds.client(enable_mqtt=False)
    await client.connect()
    yield client
    await client.disconnect()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def mqtt_client(public_creds: PublicCreds) -> AsyncIterator[EcoFlowClient]:
    """Discovered client holding the account's MQTT session for the module."""
    client = public_creds.client(enable_mqtt=True)
    await client.connect()
    if not client.mqtt_connected:
        await client.disconnect()
        pytest.fail(
            "MQTT did not connect. If another integration (e.g. Home Assistant) "
            "uses these keys, stop it first (AGENTS.md Quirk 2); if nothing else "
            "is connected, the daily client-ID quota may be spent (Quirk 1)."
        )
    yield client
    await client.disconnect()
