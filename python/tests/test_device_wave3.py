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
            "dev_sleep_state": 0,
            "wave_operating_mode": 1,
            "current_temp_set": 24.0,
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
    assert status.target_temp == pytest.approx(24.0)


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
    """set_mode(Wave3Mode.HEATING) publishes {'waveMode': 2}."""
    device = make_wave3()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_publish:
        await device.set_mode(Wave3Mode.HEATING)
    mock_publish.assert_called_once_with({"waveMode": 2})


@pytest.mark.asyncio
async def test_wave3_set_temperature_scales_to_x10() -> None:
    """set_temperature(24.0) publishes {'setTemp': 240}."""
    device = make_wave3()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_publish:
        await device.set_temperature(24.0)
    mock_publish.assert_called_once_with({"setTemp": 240})


@pytest.mark.asyncio
async def test_wave3_refresh_returns_minimal_status_on_api_error() -> None:
    """refresh() must not raise when REST returns error 1006 for Wave 3.

    The public EcoFlow Developer API returns error 1006 for Wave 3 devices
    (not allowed to get device info). refresh() must catch this and return
    a minimal Wave3Status with online=True and default field values.
    """
    from ecoflow.exceptions import EcoFlowError

    mock_rest = AsyncMock()
    mock_rest.get_quota = AsyncMock(
        side_effect=EcoFlowError(
            "API error 1006: current device is not allowed to get device info"
        )
    )

    device = Wave3Device(sn="AC71TEST", product_name="Wave 3", rest=mock_rest)
    status = await device.refresh()

    assert status is not None
    assert status.sn == "AC71TEST"
    assert status.online is True  # device is online per device list
    assert status.is_on is False  # default — no data from API
    assert status.target_temp == 22.0  # default


@pytest.mark.asyncio
async def test_wave3_refresh_with_rest_none_returns_status_without_api_call() -> None:
    """refresh() with rest=None: returns minimal status when None, then existing."""
    device = Wave3Device(sn="AC71TEST", product_name="Wave 3", rest=None)

    # First call: status=None case → returns Wave3Status with sn=AC71TEST, online=True
    status = await device.refresh()
    assert isinstance(status, Wave3Status)
    assert status.sn == "AC71TEST"
    assert status.online is True
    assert status.product_name == "Wave 3"

    # Simulate MQTT update: device receives data via MQTT
    device.status = Wave3Status(
        sn="AC71TEST", product_name="Wave 3", online=True, is_on=True
    )

    # Second call: returns existing status with is_on=True
    status2 = await device.refresh()
    assert status2.is_on is True


@pytest.mark.asyncio
async def test_wave3_refresh_with_rest_none_does_not_call_rest() -> None:
    """refresh() with rest=None must not try to call self._rest.get_quota()."""
    device = Wave3Device(sn="AC71TEST", product_name="Wave 3", rest=None)
    # If refresh() tries to call self._rest.get_quota() it will raise AttributeError
    # (None has no get_quota). This test passes if refresh() completes without raising.
    status = await device.refresh()
    assert status is not None
