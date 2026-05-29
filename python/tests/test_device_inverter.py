"""Tests for MicroInverterDevice — PowerStream feed-in power control abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.devices.inverter import MicroInverterDevice


def make_inverter() -> MicroInverterDevice:
    """Create a MicroInverterDevice with a mocked REST client."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={"pstream": {"gridWatts": 0}})
    return MicroInverterDevice(sn="PS00001", product_name="PowerStream", rest=rest)


@pytest.mark.asyncio
async def test_micro_inverter_feed_in_validates_range() -> None:
    """set_feed_in_power() raises ValueError for watts outside 0–800 range."""
    inverter = make_inverter()
    with pytest.raises(ValueError):
        await inverter.set_feed_in_power(watts=900)
    with pytest.raises(ValueError):
        await inverter.set_feed_in_power(watts=-1)


@pytest.mark.asyncio
async def test_micro_inverter_publishes_feed_in_power() -> None:
    """set_feed_in_power(watts=400) publishes {'feedInPower': 400}."""
    inverter = make_inverter()
    with patch.object(inverter, "_publish", new_callable=AsyncMock) as mock_publish:
        await inverter.set_feed_in_power(watts=400)
    mock_publish.assert_called_once_with({"feedInPower": 400})
