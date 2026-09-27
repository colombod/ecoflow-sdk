"""Live tier 2 — read-only MQTT. Holds the account's single MQTT session for
the duration of the module (a minute or two). Stop Home Assistant or any other
integration using the same keys first (AGENTS.md Quirk 2).

    uv run pytest tests/e2e/test_live_mqtt.py --live=mqtt -v -s

For each device it waits for real MQTT pushes, then checks that the status
decoded from MQTT agrees with a REST refresh on stable fields (capacity,
cycles, voltage, SOC). This is what catches envelope/parsing regressions —
an all-zero MQTT status fails here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ecoflow.client import EcoFlowClient
from tests.e2e.conftest import MqttTiming
from tests.support.consistency import compare

pytestmark = [
    pytest.mark.integration,
    pytest.mark.replayable,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.timeout(300),
]


def _current(device: Any) -> Any:  # noqa: ANN401
    return getattr(device, "status", None) or getattr(device, "data", None)


async def _mqtt_snapshot(device: Any, timing: MqttTiming) -> Any:  # noqa: ANN401
    if _current(device) is None:
        async with asyncio.timeout(timing.first_push_timeout_s):
            await device.wait_for_update()
    await asyncio.sleep(timing.settle_s)  # remaining chunks of the state dump
    return _current(device)


async def test_mqtt_session_is_live(mqtt_client: EcoFlowClient) -> None:
    assert mqtt_client.mqtt_connected
    typed = mqtt_client.stream_units + mqtt_client.meters + mqtt_client.plugs
    for device in typed + mqtt_client.batteries:
        assert device.sn in mqtt_client.mqtt_subscriptions


async def test_mqtt_status_agrees_with_rest(
    mqtt_client: EcoFlowClient, rest_client: EcoFlowClient, mqtt_timing: MqttTiming
) -> None:
    targets = (
        mqtt_client.stream_units
        + mqtt_client.meters
        + mqtt_client.plugs
        + mqtt_client.batteries
    )
    rest_devices: dict[str, Any] = {
        d.sn: d
        for d in rest_client.stream_units
        + rest_client.meters
        + rest_client.plugs
        + rest_client.batteries
    }
    if not targets:
        pytest.skip("no STREAM / meter / plug / battery devices on this account")

    failures: list[str] = []
    for device in targets:
        label = f"{type(device).__name__} {device.sn[:4]}…"
        try:
            mqtt_status = await _mqtt_snapshot(device, mqtt_timing)
        except TimeoutError:
            failures.append(
                f"{label}: no MQTT push within {mqtt_timing.first_push_timeout_s}s"
            )
            continue
        # From the REST-only client: this device's own refresh() would merge
        # REST into its MQTT state (STREAM) and compare the pushes with themselves.
        rest_status = await rest_devices[device.sn].refresh()
        if not compare(mqtt_status, mqtt_status).compared:
            failures.append(f"{label}: MQTT status has no populated stable fields")
            continue
        if not compare(rest_status, rest_status).compared:
            # Seen live: the Smart Meter's quota/all is empty and cascade-slave
            # STREAM units report cmsBattSoc=0 — REST has nothing to compare.
            print(f"\n[{label}] MQTT parsed; REST has no stable fields to compare")
            continue
        result = compare(mqtt_status, rest_status)
        print(f"\n[{label}] compared={result.compared} mismatches={result.mismatches}")
        if not result.compared:
            failures.append(f"{label}: MQTT and REST share no populated stable field")
        failures += [f"{label}: {m}" for m in result.mismatches]
    assert not failures, "\n".join(failures)


async def test_client_events_stream_delivers(
    mqtt_client: EcoFlowClient, mqtt_timing: MqttTiming
) -> None:
    """EcoFlowClient.events() yields real updates from the live session."""
    stream = mqtt_client.events()
    try:
        async with asyncio.timeout(mqtt_timing.first_push_timeout_s):
            event = await anext(stream)
    finally:
        await stream.aclose()
    assert event["sn"] and event["data"] is not None
