"""Tests for Wave3Device — mode/temperature/fan controls for Wave 3 portable AC."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.devices.wave3 import Wave3Device
from ecoflow.models.wave3 import Wave3Mode, Wave3Status


def make_wave3() -> Wave3Device:
    """Create a Wave3Device with a mocked REST client."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(
        return_value={
            "pd": {
                "powerMode": 1,
                "waveMode": 0,
                "setTemp": 240,
            }
        }
    )
    return Wave3Device(sn="WAVE3-001", product_name="Wave 3", rest=rest)


@pytest.mark.asyncio
async def test_wave3_refresh_returns_status() -> None:
    """refresh() returns a Wave3Status with is_on=True and target_temp==24.0."""
    device = make_wave3()
    status = await device.refresh()
    assert isinstance(status, Wave3Status)
    assert status.is_on is True
    assert status.target_temp == 24.0


@pytest.mark.asyncio
async def test_wave3_set_temperature_validates_range() -> None:
    """set_temperature() raises ValueError for temps outside 16.0–30.0."""
    device = make_wave3()
    with pytest.raises(ValueError):
        await device.set_temperature(15.0)
    with pytest.raises(ValueError):
        await device.set_temperature(31.0)


@pytest.mark.asyncio
async def test_wave3_set_fan_speed_validates() -> None:
    """set_fan_speed() raises ValueError for level=4 (valid: 0, 1, 2, 3)."""
    device = make_wave3()
    with pytest.raises(ValueError):
        await device.set_fan_speed(4)


@pytest.mark.asyncio
async def test_wave3_turn_on_publishes_power_mode_1() -> None:
    """turn_on() publishes {'powerMode': 1}."""
    device = make_wave3()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_publish:
        await device.turn_on()
    mock_publish.assert_called_once_with({"powerMode": 1})


@pytest.mark.asyncio
async def test_wave3_set_mode_publishes_int_value() -> None:
    """set_mode(Wave3Mode.HEAT) publishes {'waveMode': 1}."""
    device = make_wave3()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_publish:
        await device.set_mode(Wave3Mode.HEAT)
    mock_publish.assert_called_once_with({"waveMode": 1})


@pytest.mark.asyncio
async def test_wave3_set_temperature_scales_to_x10() -> None:
    """set_temperature(24.0) publishes {'setTemp': 240}."""
    device = make_wave3()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_publish:
        await device.set_temperature(24.0)
    mock_publish.assert_called_once_with({"setTemp": 240})
