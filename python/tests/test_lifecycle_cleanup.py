"""Offline cleanup contracts for lifecycle owners; no broker is contacted."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.client import EcoFlowClient
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport


async def test_client_closes_rest_even_if_mqtt_cleanup_fails() -> None:
    with patch("ecoflow.client.RestTransport") as rest_cls:
        rest_cls.return_value.close = AsyncMock()
        client = EcoFlowClient("test", "test")
        mqtt = MagicMock()
        mqtt.disconnect = AsyncMock(side_effect=RuntimeError("cleanup failed"))
        client._mqtt = mqtt  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await client.disconnect()
        rest_cls.return_value.close.assert_awaited_once()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_context_entry_closes_resources(cancelled: bool) -> None:
    with patch("ecoflow.client.RestTransport") as rest_cls:
        rest_cls.return_value.close = AsyncMock()
        error = (
            asyncio.CancelledError() if cancelled else RuntimeError("discovery failed")
        )
        rest_cls.return_value.list_devices = AsyncMock(side_effect=error)
        client = EcoFlowClient("test", "test", enable_mqtt=False)
        with pytest.raises(type(error)):
            await client.__aenter__()
        rest_cls.return_value.close.assert_awaited_once()


@pytest.mark.timeout(2)
async def test_cancelled_mqtt_connect_stops_owned_background_task() -> None:
    transport = MqttTransport(
        MqttCredentials("offline.invalid", 8883, "mqtts", "u", "p", "c", "test")
    )
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def background() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    with patch.object(transport, "_run", background):
        task = asyncio.create_task(transport.connect())
        try:
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stopped.is_set()
            assert not transport.connected
        finally:
            await transport.disconnect()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_entry_cleanup_failure_preserves_original_error(cancelled: bool) -> None:
    with patch("ecoflow.client.RestTransport") as rest_cls:
        error = (
            asyncio.CancelledError() if cancelled else RuntimeError("discovery failed")
        )
        rest_cls.return_value.list_devices = AsyncMock(side_effect=error)
        rest_cls.return_value.close = AsyncMock(side_effect=ValueError("close failed"))
        client = EcoFlowClient("test", "test", enable_mqtt=False)
        with pytest.raises(type(error)) as caught:
            await client.__aenter__()
        assert caught.value is error
        assert any("ValueError" in note for note in error.__notes__)
        rest_cls.return_value.close.assert_awaited_once()


async def test_disconnect_cleanup_failure_preserves_first_error() -> None:
    with patch("ecoflow.client.RestTransport") as rest_cls:
        error = RuntimeError("MQTT cleanup failed")
        rest_cls.return_value.close = AsyncMock(side_effect=ValueError("close failed"))
        client = EcoFlowClient("test", "test")
        mqtt = MagicMock()
        mqtt.disconnect = AsyncMock(side_effect=error)
        client._mqtt = mqtt  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(RuntimeError, match="MQTT cleanup failed") as caught:
            await client.disconnect()
        assert caught.value is error
        assert any("ValueError" in note for note in error.__notes__)
        rest_cls.return_value.close.assert_awaited_once()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_context_body_error_survives_cleanup_failure(cancelled: bool) -> None:
    with patch("ecoflow.client.RestTransport") as rest_cls:
        rest_cls.return_value.list_devices = AsyncMock(return_value=[])
        rest_cls.return_value.close = AsyncMock(side_effect=ValueError("close failed"))
        client = EcoFlowClient("test", "test", enable_mqtt=False)
        error = asyncio.CancelledError() if cancelled else RuntimeError("body failed")
        with pytest.raises(type(error)) as caught:
            async with client:
                raise error
        assert caught.value is error
        assert any("ValueError" in note for note in error.__notes__)
        rest_cls.return_value.close.assert_awaited_once()
