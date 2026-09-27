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

from ecoflow.client import EcoFlowClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_rest,
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


async def test_quota_all_is_signed_and_parses(rest_client: EcoFlowClient) -> None:
    """quota/all?sn=… succeeds (signature incl. params) and parses non-zero."""
    targets = (
        rest_client.stream_units
        + rest_client.meters
        + rest_client.plugs
        + rest_client.batteries
    )
    if not targets:
        pytest.skip("no STREAM / meter / plug / battery devices on this account")
    for device in targets:
        status = await device.refresh()
        populated = _populated(status)
        print(f"\n[{type(device).__name__} {device.sn[:4]}…] non-zero: {populated}")
        assert populated, f"{device.sn[:4]}…: REST parsed to all-zero {status!r}"
