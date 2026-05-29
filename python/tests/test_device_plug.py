"""Tests for SmartPlugDevice — on/off/toggle/brightness/max_watts controls."""

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
async def test_turn_on_publishes_cmdcode_format() -> None:
    """turn_on() publishes WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE with plugSwitch=1."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.turn_on()
    mock_publish.assert_called_once_with(
        {
            "cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE",
            "params": {"plugSwitch": 1},
        }
    )


@pytest.mark.asyncio
async def test_turn_off_publishes_cmdcode_format() -> None:
    """turn_off() publishes WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE with plugSwitch=0."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.turn_off()
    mock_publish.assert_called_once_with(
        {
            "cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE",
            "params": {"plugSwitch": 0},
        }
    )


@pytest.mark.asyncio
async def test_toggle_turns_off_when_on() -> None:
    """After refresh() with is_on=True, toggle() publishes cmdCode with plugSwitch=0."""
    plug = make_plug(is_on=True)
    await plug.refresh()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.toggle()
    mock_publish.assert_called_once_with(
        {
            "cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE",
            "params": {"plugSwitch": 0},
        }
    )


@pytest.mark.asyncio
async def test_set_brightness_validates_max_range() -> None:
    """set_brightness() raises ValueError for level > 1023."""
    plug = make_plug()
    with pytest.raises(ValueError, match="1023"):
        await plug.set_brightness(1024)


@pytest.mark.asyncio
async def test_set_brightness_validates_min_range() -> None:
    """set_brightness() raises ValueError for level < 0."""
    plug = make_plug()
    with pytest.raises(ValueError):
        await plug.set_brightness(-1)


@pytest.mark.asyncio
async def test_set_brightness_publishes_cmdcode_format() -> None:
    """set_brightness() publishes cmdCode=WN511_SOCKET_SET_BRIGHTNESS_PACK."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.set_brightness(512)
    mock_publish.assert_called_once_with(
        {
            "cmdCode": "WN511_SOCKET_SET_BRIGHTNESS_PACK",
            "params": {"brightness": 512},
        }
    )


@pytest.mark.asyncio
async def test_set_brightness_accepts_boundary_values() -> None:
    """set_brightness() accepts 0 and 1023 (boundary values)."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock):
        await plug.set_brightness(0)
        await plug.set_brightness(1023)


@pytest.mark.asyncio
async def test_set_max_watts_publishes_cmdcode_format() -> None:
    """set_max_watts() publishes cmdCode=WN511_SOCKET_SET_MAX_WATTS."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock) as mock_publish:
        await plug.set_max_watts(1500)
    mock_publish.assert_called_once_with(
        {
            "cmdCode": "WN511_SOCKET_SET_MAX_WATTS",
            "params": {"maxWatts": 1500},
        }
    )


@pytest.mark.asyncio
async def test_set_max_watts_validates_max_range() -> None:
    """set_max_watts() raises ValueError for max_watts > 2500."""
    plug = make_plug()
    with pytest.raises(ValueError, match="2500"):
        await plug.set_max_watts(2501)


@pytest.mark.asyncio
async def test_set_max_watts_validates_min_range() -> None:
    """set_max_watts() raises ValueError for max_watts < 0."""
    plug = make_plug()
    with pytest.raises(ValueError):
        await plug.set_max_watts(-1)


@pytest.mark.asyncio
async def test_set_max_watts_accepts_boundary_values() -> None:
    """set_max_watts() accepts 0 and 2500 (boundary values)."""
    plug = make_plug()
    with patch.object(plug, "_publish", new_callable=AsyncMock):
        await plug.set_max_watts(0)
        await plug.set_max_watts(2500)
