"""Tests for SmartPlugDevice — on/off/toggle/brightness control abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.models.plug import SmartPlugData

# Real REST /quota/all flat format (confirmed from live HW52-series device, 2026-05)
_QUOTA_RESPONSE_ON = {
    "2_1.switchSta": True,
    "2_1.watts": 1230,
    "2_1.volt": 230,
    "2_1.current": 540,
    "2_1.temp": 30,
    "2_1.brightness": 1023,
    "2_1.runTime": 3600,
}

_QUOTA_RESPONSE_OFF = {
    "2_1.switchSta": False,
    "2_1.watts": 0,
    "2_1.volt": 230,
    "2_1.current": 0,
    "2_1.temp": 25,
    "2_1.brightness": 0,
    "2_1.runTime": 0,
}


def make_plug(*, is_on: bool = True) -> SmartPlugDevice:
    """Create a SmartPlugDevice with a mocked REST client returning quota/all format."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(
        return_value=_QUOTA_RESPONSE_ON if is_on else _QUOTA_RESPONSE_OFF
    )
    return SmartPlugDevice(sn="SP00001", product_name="Smart Plug", rest=rest)


@pytest.mark.asyncio
async def test_plug_refresh_returns_data() -> None:
    """refresh() returns a SmartPlugData with is_on=True."""
    plug = make_plug(is_on=True)
    data = await plug.refresh()
    assert isinstance(data, SmartPlugData)
    assert data.is_on is True


@pytest.mark.asyncio
async def test_turn_on_publishes_switch_1() -> None:
    """turn_on() publishes {'switch': 1}."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.turn_on()
    mock_publish.assert_called_once_with({"switch": 1})


@pytest.mark.asyncio
async def test_turn_off_publishes_switch_0() -> None:
    """turn_off() publishes {'switch': 0}."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.turn_off()
    mock_publish.assert_called_once_with({"switch": 0})


@pytest.mark.asyncio
async def test_toggle_turns_off_when_on() -> None:
    """After refresh() with is_on=True, toggle() publishes {'switch': 0}."""
    plug = make_plug(is_on=True)
    await plug.refresh()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.toggle()
    mock_publish.assert_called_once_with({"switch": 0})


@pytest.mark.asyncio
async def test_set_brightness_validates_range() -> None:
    """set_brightness() raises ValueError for level > 100."""
    plug = make_plug()
    with pytest.raises(ValueError):
        await plug.set_brightness(101)
