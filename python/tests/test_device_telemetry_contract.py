"""Adapter contracts shared across the three supported telemetry families."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ecoflow.devices.meter import SmartMeterDevice
from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.devices.stream_ultra import StreamUltraDevice
from ecoflow.exceptions import EcoFlowConnectionError

Device = SmartMeterDevice | SmartPlugDevice | StreamUltraDevice

CASES = [
    (SmartMeterDevice, "powGetSysGrid", 12, "gridConnectionVolL1", "grid_power_watts"),
    (StreamUltraDevice, "powGetSysGrid", 12, "gridConnectionVol", "grid_power_watts"),
    (SmartPlugDevice, "2_1.watts", 120, "2_1.volt", "power_watts"),
]


def current(device: Device) -> Any:
    return getattr(device, "data", None) or getattr(device, "status", None)


@pytest.mark.parametrize("kind,power,value,voltage,attr", CASES)
@pytest.mark.parametrize("via_rest", [False, True])
async def test_rejected_payload_cannot_poison_future_updates(
    kind: type[Device],
    power: str,
    value: int,
    voltage: str,
    attr: str,
    via_rest: bool,
) -> None:
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={power: "invalid"})
    device = kind(sn="TEST", product_name="test", rest=rest)
    updates: list[Any] = []
    device.on_update(updates.append)
    device._handle_message(device.sn, {power: value})  # pyright: ignore[reportPrivateUsage]
    before = current(device)
    times = device.field_received_at
    with pytest.raises((TypeError, ValueError)):
        if via_rest:
            await device.refresh()
        else:
            device._handle_message(device.sn, {power: "invalid"})  # pyright: ignore[reportPrivateUsage]
    assert current(device) is before
    assert device.field_received_at == times
    assert len(updates) == 1
    device._handle_message(device.sn, {voltage: 230})  # pyright: ignore[reportPrivateUsage]
    assert getattr(current(device), attr) == 12
    assert device.field_received_at[power] == times[power]
    assert len(updates) == 2


@pytest.mark.parametrize("kind,power,value,voltage,attr", CASES)
async def test_quota_error_preserves_state(
    kind: type[Device],
    power: str,
    value: int,
    voltage: str,
    attr: str,
) -> None:
    rest = MagicMock()
    rest.get_quota = AsyncMock(side_effect=EcoFlowConnectionError("offline"))
    device = kind(sn="TEST", product_name="test", rest=rest)
    device._handle_message(device.sn, {power: value})  # pyright: ignore[reportPrivateUsage]
    before = current(device)
    times = device.field_received_at
    with pytest.raises(EcoFlowConnectionError, match="offline"):
        await device.refresh()
    assert current(device) is before
    assert device.field_received_at == times
