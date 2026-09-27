"""Shared fixtures for live E2E tests.

Credentials come from tests/.env (gitignored) or the shell. Nothing here runs
unless pytest is invoked with ``--live`` (see tests/conftest.py).

Each fixture opens ONE client per test module. The MQTT fixture holds the
account's single broker session for the module's duration; stop any other
integration using the same keys (e.g. Home Assistant) first — AGENTS.md
Quirk 2 — or it will be disconnected, or this run will fail with error 135.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio

from ecoflow.client import EcoFlowClient


@dataclass(frozen=True)
class PublicCreds:
    access_key: str
    secret_key: str
    region: str

    def client(self, *, enable_mqtt: bool) -> EcoFlowClient:
        return EcoFlowClient(
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            enable_mqtt=enable_mqtt,
        )


@pytest.fixture(scope="session")
def public_creds() -> PublicCreds:
    access_key = os.getenv("ECOFLOW_ACCESS_KEY", "")
    secret_key = os.getenv("ECOFLOW_SECRET_KEY", "")
    if not (access_key and secret_key):
        pytest.skip("ECOFLOW_ACCESS_KEY / ECOFLOW_SECRET_KEY not set (tests/.env)")
    return PublicCreds(access_key, secret_key, os.getenv("ECOFLOW_REGION", "EU"))


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
