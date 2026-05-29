"""Tests for SmartMeterDevice — read-only smart meter abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ecoflow.devices.meter import SmartMeterDevice
from ecoflow.models.meter import SmartMeterData

# Real BK21 MQTT quota format (confirmed from live device 2026-05-29)
_QUOTA_RESPONSE = {
    "powGetSysGrid": 4917.057,
    "gridConnectionSta": "PANEL_GRID_IN",
    "gridConnectionVolL1": 237.38,
    "gridConnectionAmpL1": 21.61,
    "gridConnectionFlagL1": True,
}


def make_meter() -> SmartMeterDevice:
    """Create a SmartMeterDevice with a mocked REST client."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value=_QUOTA_RESPONSE)
    return SmartMeterDevice(sn="SM00001", product_name="Smart Meter", rest=rest)


@pytest.mark.asyncio
async def test_smart_meter_refresh_returns_data() -> None:
    """refresh() returns a SmartMeterData with grid_power_watts from powGetSysGrid."""
    meter = make_meter()
    data = await meter.refresh()
    assert isinstance(data, SmartMeterData)
    assert data.grid_power_watts == pytest.approx(4917.057)  # pyright: ignore[reportUnknownMemberType]


def test_meter_is_read_only_no_action_methods() -> None:
    """SmartMeterDevice has no turn_on or turn_off methods."""
    meter = make_meter()
    assert not hasattr(meter, "turn_on")
    assert not hasattr(meter, "turn_off")


def test_smart_meter_accumulates_mqtt_chunks() -> None:
    """MQTT data arrives in chunks; data must merge all chunks not just last."""
    meter = SmartMeterDevice(
        sn="BK21TEST", product_name="Smart Meter", rest=MagicMock()
    )

    # Chunk 1: total grid power only — no per-phase data
    meter._handle_message("BK21TEST", {"powGetSysGrid": 5183.0})  # pyright: ignore[reportPrivateUsage]
    assert meter.data is not None
    assert meter.data.grid_power_watts == pytest.approx(5183.0)  # pyright: ignore[reportUnknownMemberType]
    assert meter.data.voltage_l1 == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]  # Not arrived yet

    # Chunk 2: per-phase voltage — grid power not repeated
    meter._handle_message(  # pyright: ignore[reportPrivateUsage]
        "BK21TEST",
        {"gridConnectionVolL1": 237.38, "gridConnectionFlagL1": True},
    )
    assert meter.data is not None
    # Grid power MUST still be 5183W (preserved from chunk 1, not reset to 0)
    assert meter.data.grid_power_watts == pytest.approx(5183.0)  # pyright: ignore[reportUnknownMemberType]
    assert meter.data.voltage_l1 == pytest.approx(237.38)  # pyright: ignore[reportUnknownMemberType]
    assert meter.data.phase_l1_active is True
