"""Tests for BaseDevice abstraction."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ecoflow.devices.base import BaseDevice
from ecoflow.exceptions import EcoFlowConnectionError


def _make_rest() -> MagicMock:
    rest = MagicMock()
    rest.set_quota = AsyncMock(return_value={})
    return rest


def _make_mqtt(*, connected: bool = True) -> MagicMock:
    mqtt = MagicMock()
    mqtt.connected = connected
    mqtt.publish = AsyncMock()
    mqtt.creds = MagicMock()
    mqtt.creds.user_id = "user123"
    return mqtt


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
async def test_base_device_publish_raises_when_no_mqtt() -> None:
    """_publish raises EcoFlowConnectionError when MQTT is not connected.

    BEHAVIOR CHANGE: _publish no longer falls back to REST — it uses the
    public-API TOPIC_OPEN_SET topic and raises if MQTT is unavailable.
    """
    rest = _make_rest()
    device = BaseDevice(sn="SN12345", product_name="Smart Plug", rest=rest, mqtt=None)
    with pytest.raises(EcoFlowConnectionError):
        await device._publish({"cmdCode": "TEST", "params": {}})  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_base_device_publish_uses_open_set_topic() -> None:
    """_publish publishes to TOPIC_OPEN_SET (/open/{user_id}/{sn}/set)."""
    from ecoflow.const import TOPIC_OPEN_SET

    rest = _make_rest()
    mqtt = _make_mqtt(connected=True)
    device = BaseDevice(sn="SN12345", product_name="Smart Plug", rest=rest, mqtt=mqtt)
    payload = {"cmdCode": "TEST", "params": {"key": 1}}
    await device._publish(payload)  # pyright: ignore[reportPrivateUsage]

    expected_topic = TOPIC_OPEN_SET.format(user_id="user123", sn="SN12345")
    mqtt.publish.assert_called_once_with(expected_topic, payload)


@pytest.mark.asyncio
async def test_base_device_publish_raises_when_mqtt_disconnected() -> None:
    """_publish raises EcoFlowConnectionError when MQTT exists but is not connected."""
    rest = _make_rest()
    mqtt = _make_mqtt(connected=False)
    device = BaseDevice(sn="SN12345", product_name="Smart Plug", rest=rest, mqtt=mqtt)
    with pytest.raises(EcoFlowConnectionError):
        await device._publish({"cmdCode": "TEST"})  # pyright: ignore[reportPrivateUsage]
