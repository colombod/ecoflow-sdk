"""Live tier 1 — REST only. Never opens MQTT, so it is safe to run while
another integration (e.g. Home Assistant) is connected with the same keys.

    uv run pytest tests/e2e/test_live_rest.py --live=rest -v

Validates request signing (device list has no params; quota/all is signed
with ``sn``) and that each supported device parses to non-zero data.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from ecoflow.auth import EcoFlowCredentials
from ecoflow.client import EcoFlowClient
from ecoflow.transport.rest import RestTransport
from tests.e2e.conftest import PublicCreds

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_rest,
    pytest.mark.replayable,
    pytest.mark.asyncio(loop_scope="module"),
]


def _populated(status: Any) -> list[str]:  # noqa: ANN401
    """Names of numeric fields that are non-zero."""
    return [
        f.name
        for f in fields(status)
        if isinstance(getattr(status, f.name), int | float)
        and not isinstance(getattr(status, f.name), bool)
        and getattr(status, f.name) != 0
    ]


async def test_device_list_is_signed_and_returns_devices(
    rest_client: EcoFlowClient,
) -> None:
    devices = (
        rest_client.stream_units
        + rest_client.meters
        + rest_client.plugs
        + rest_client.batteries
        + rest_client.inverters
        + rest_client.wave3_units
    )
    assert devices or rest_client.unknown_devices, "account returned no devices"
    assert rest_client.mqtt_connected is False
    for d in rest_client.unknown_devices:
        print(f"\n[unknown device] {d.product_name!r} sn-prefix={d.sn[:4]}")


async def test_quota_all_is_signed_and_parses(
    rest_client: EcoFlowClient, public_creds: PublicCreds
) -> None:
    """quota/all?sn=… succeeds (signature incl. params) and parses non-zero.

    A device whose quota/all ``data`` is genuinely empty is reported, not
    failed — seen live for the (online) Smart Meter, which only reports over
    MQTT. Any device that does return data must parse to non-zero values.
    """
    targets = (
        rest_client.stream_units
        + rest_client.meters
        + rest_client.plugs
        + rest_client.batteries
    )
    if not targets:
        pytest.skip("no STREAM / meter / plug / battery devices on this account")
    creds = EcoFlowCredentials(public_creds.access_key, public_creds.secret_key)
    parsed = 0
    async with RestTransport(creds, region=public_creds.region) as rest:
        for device in targets:
            label = f"{type(device).__name__} {device.sn[:4]}…"
            if not await rest.get_quota(device.sn):
                print(f"\n[{label}] quota/all returned no data")
                continue
            status = await device.refresh()
            populated = _populated(status)
            print(f"\n[{label}] non-zero: {populated}")
            assert populated, f"{label}: REST parsed to all-zero {status!r}"
            parsed += 1
    assert parsed, "no device returned quota data"
