"""Tests for BaseDevice abstraction."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ecoflow.devices.base import BaseDevice


def _make_rest() -> MagicMock:
    rest = MagicMock()
    rest.set_quota = AsyncMock(return_value={})
    return rest


def test_base_device_construction() -> None:
    rest = _make_rest()
    device = BaseDevice(sn="SN12345", product_name="Smart Plug", rest=rest)
    assert device.sn == "SN12345"
    assert device.product_name == "Smart Plug"


def test_base_device_repr() -> None:
    rest = _make_rest()
    device = BaseDevice(sn="SN12345", product_name="Smart Plug", rest=rest)
    r = repr(device)
    assert "SN12345" in r
    assert "Smart Plug" in r


@pytest.mark.asyncio
async def test_base_device_publish_uses_rest_when_no_mqtt() -> None:
    rest = _make_rest()
    device = BaseDevice(sn="SN12345", product_name="Smart Plug", rest=rest, mqtt=None)
    await device._publish({"switch": 1})
    rest.set_quota.assert_called_once_with("SN12345", {"switch": 1})
