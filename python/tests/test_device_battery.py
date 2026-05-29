"""Tests for BatteryDevice — charge/discharge control abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.devices.battery import BatteryDevice
from ecoflow.models.battery import BatteryStatus

_QUOTA_RESPONSE = {
    "pd": {"soc": 75, "dsgRemTime": 120, "wattsOutSum": 100},
    "inv": {"outputWatts": 100, "cfgAcEnabled": 1},
}


def make_battery() -> BatteryDevice:
    """Create a BatteryDevice with a mocked REST client."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value=_QUOTA_RESPONSE)
    return BatteryDevice(sn="SN99001", product_name="Delta Max", rest=rest)


@pytest.mark.asyncio
async def test_battery_refresh_returns_status() -> None:
    """refresh() returns a BatteryStatus with soc and ac_output_enabled populated."""
    battery = make_battery()
    status = await battery.refresh()
    assert isinstance(status, BatteryStatus)
    assert status.soc == 75.0
    assert status.ac_output_enabled is True


@pytest.mark.asyncio
async def test_battery_status_cached_after_refresh() -> None:
    """After refresh(), battery.status is the same object returned by refresh()."""
    battery = make_battery()
    status = await battery.refresh()
    assert battery.status is status


@pytest.mark.asyncio
async def test_set_ac_output_publishes_command() -> None:
    """set_ac_output(enabled=True) publishes {'cfgAcEnabled': 1}."""
    battery = make_battery()
    with patch.object(battery, "_publish", new_callable=AsyncMock) as mock_publish:
        await battery.set_ac_output(enabled=True)
    mock_publish.assert_called_once_with({"cfgAcEnabled": 1})


@pytest.mark.asyncio
async def test_set_charge_limit_validates_range() -> None:
    """set_charge_limit raises ValueError for out-of-range soc_pct values."""
    battery = make_battery()
    with pytest.raises(ValueError):
        await battery.set_charge_limit(soc_pct=30)  # too low (min is 50)
    with pytest.raises(ValueError):
        await battery.set_charge_limit(soc_pct=101)  # too high (max is 100)
