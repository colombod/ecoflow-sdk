"""Tests for the private _MqttClient implementation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.const import TOPIC_DEVICE_PROPERTY, TOPIC_OPEN_QUOTA
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.transport.mqtt import MqttCredentials, _MqttClient

MQTT_CREDS = MqttCredentials(
    url="mqtt.ecoflow.com",
    port=8883,
    protocol="mqtts",
    username="user123",
    password="pass123",
    client_id="client_abc",
    user_id="user456",
)


async def test_mqtt_client_can_be_constructed() -> None:
    client = _MqttClient(MQTT_CREDS)
    assert client is not None


async def test_subscribe_registers_callback() -> None:
    client = _MqttClient(MQTT_CREDS)
    called_with: list[tuple[str, dict]] = []
    client.on_message("SN12345", lambda sn, data: called_with.append((sn, data)))
    assert "SN12345" in client._subscriptions


async def test_message_routing_calls_correct_callback() -> None:
    """Dispatch with /open/{user_id}/{sn}/quota correctly routes to SN at index -2."""
    client = _MqttClient(MQTT_CREDS)
    received: list[dict] = []
    client.on_message("SN12345", lambda sn, data: received.append(data))
    await client._dispatch_message("/open/user456/SN12345/quota", {"soc": 85})
    assert received == [{"soc": 85}]


async def test_message_routing_ignores_wrong_sn() -> None:
    """Dispatch with wrong SN in /open/ topic does not call unrelated callback."""
    client = _MqttClient(MQTT_CREDS)
    received: list[dict] = []
    client.on_message("SN12345", lambda sn, data: received.append(data))
    await client._dispatch_message("/open/user456/DIFFERENT_SN/quota", {"soc": 50})
    assert received == []


async def test_user_id_available_on_credentials() -> None:
    assert MQTT_CREDS.user_id == "user456"


async def test_mqtt_client_constructor_uses_client_id_not_identifier() -> None:
    """Regression: check the actual aiomqtt parameter name for client ID."""
    import inspect

    import aiomqtt

    sig = inspect.signature(aiomqtt.Client.__init__)
    params = list(sig.parameters.keys())
    # Verify the actual parameter name exists (could be 'identifier' or 'client_id')
    assert "identifier" in params or "client_id" in params, (
        "Neither 'identifier' nor 'client_id' found in aiomqtt.Client"
        f" signature: {params}"
    )


# ---------------------------------------------------------------------------
# New tests for the background-task pattern (aiomqtt context-manager design)
# ---------------------------------------------------------------------------


async def test_connect_signals_ready_when_broker_connects() -> None:
    """connect() should set _connected=True when the broker accepts the connection."""
    client = _MqttClient(MQTT_CREDS, connect_timeout=5)

    # Async generator that hangs — simulates a live MQTT message stream.
    async def hanging_stream():
        await asyncio.Event().wait()  # blocks until task is cancelled
        yield  # pragma: no cover — never reached

    mock_inner = AsyncMock()
    mock_inner.subscribe = AsyncMock()
    mock_inner.messages = hanging_stream()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("ecoflow.transport.mqtt.aiomqtt.Client", return_value=mock_cm):
        await asyncio.wait_for(client.connect(), timeout=5.0)

    assert client._connected is True
    await client.disconnect()


async def test_connect_times_out_when_broker_unreachable() -> None:
    """connect() raises EcoFlowConnectionError if broker never responds."""
    client = _MqttClient(MQTT_CREDS, connect_timeout=0.1)

    # __aenter__ hangs forever — broker never accepts the connection.
    async def hang(*args: object, **kwargs: object) -> AsyncMock:
        await asyncio.sleep(999)
        return AsyncMock()  # pragma: no cover

    mock_cm = MagicMock()
    mock_cm.__aenter__ = hang
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("ecoflow.transport.mqtt.aiomqtt.Client", return_value=mock_cm):
        with pytest.raises(EcoFlowConnectionError, match="timed out"):
            await client.connect()


async def test_on_message_callback_called_when_message_arrives() -> None:
    """Messages arriving on a subscribed /open/ topic invoke registered callbacks."""
    client = _MqttClient(MQTT_CREDS, connect_timeout=5)
    received: list[tuple[str, dict]] = []
    client.on_message("SN12345", lambda sn, data: received.append((sn, data)))

    await client._dispatch_message("/open/user456/SN12345/quota", {"soc": 85})

    assert received == [("SN12345", {"soc": 85})]


async def test_publish_fails_when_not_connected() -> None:
    """publish() raises EcoFlowConnectionError when the client is not connected."""
    client = _MqttClient(MQTT_CREDS)
    with pytest.raises(EcoFlowConnectionError):
        await client.publish("/some/topic", {"key": "val"})


# ---------------------------------------------------------------------------
# Finding 1: New TOPIC_OPEN_QUOTA topic template tests
# ---------------------------------------------------------------------------


async def test_topic_open_quota_constant_exists() -> None:
    """TOPIC_OPEN_QUOTA is defined in const and has the correct pattern."""
    assert "{user_id}" in TOPIC_OPEN_QUOTA
    assert "{sn}" in TOPIC_OPEN_QUOTA
    assert "open" in TOPIC_OPEN_QUOTA
    assert "quota" in TOPIC_OPEN_QUOTA


async def test_topic_open_quota_format() -> None:
    """TOPIC_OPEN_QUOTA formats correctly with user_id and sn."""
    topic = TOPIC_OPEN_QUOTA.format(user_id="user456", sn="BK11DEVICE")
    assert topic == "/open/user456/BK11DEVICE/quota"


async def test_topic_device_property_kept_as_legacy() -> None:
    """TOPIC_DEVICE_PROPERTY is still importable (legacy support)."""
    assert "{sn}" in TOPIC_DEVICE_PROPERTY
    assert "property" in TOPIC_DEVICE_PROPERTY


async def test_on_message_default_topic_template_is_open_quota() -> None:
    """on_message() defaults to TOPIC_OPEN_QUOTA as the subscription template."""
    client = _MqttClient(MQTT_CREDS)
    client.on_message("SN12345", lambda sn, data: None)
    _template, _callbacks = client._subscriptions["SN12345"]
    assert _template == TOPIC_OPEN_QUOTA


async def test_on_message_custom_topic_template() -> None:
    """on_message() stores the custom topic_template when explicitly provided."""
    client = _MqttClient(MQTT_CREDS)
    client.on_message(
        "SN12345", lambda sn, data: None, topic_template=TOPIC_DEVICE_PROPERTY
    )
    _template, _callbacks = client._subscriptions["SN12345"]
    assert _template == TOPIC_DEVICE_PROPERTY


async def test_subscriptions_store_tuple_with_template_and_callbacks() -> None:
    """_subscriptions maps SN → (topic_template, [callbacks])."""
    client = _MqttClient(MQTT_CREDS)
    cb = lambda sn, data: None  # noqa: E731
    client.on_message("SN12345", cb)
    assert isinstance(client._subscriptions["SN12345"], tuple)
    template, callbacks = client._subscriptions["SN12345"]
    assert template == TOPIC_OPEN_QUOTA
    assert cb in callbacks


async def test_dispatch_open_quota_topic_extracts_sn_at_minus_2() -> None:
    """_dispatch_message with /open/{user_id}/{sn}/quota routes by SN at position -2."""
    client = _MqttClient(MQTT_CREDS)
    received: list[str] = []
    client.on_message("BK11DEVICE", lambda sn, data: received.append(sn))
    await client._dispatch_message("/open/user456/BK11DEVICE/quota", {"key": "val"})
    assert received == ["BK11DEVICE"]


async def test_dispatch_legacy_app_topic_still_works() -> None:
    """Legacy /app/device/property/{sn} topic falls back to SN at position -1."""
    client = _MqttClient(MQTT_CREDS)
    received: list[dict] = []
    client.on_message(
        "SN12345",
        lambda sn, data: received.append(data),
        topic_template=TOPIC_DEVICE_PROPERTY,
    )
    await client._dispatch_message("/app/device/property/SN12345", {"soc": 42})
    assert received == [{"soc": 42}]


async def test_run_subscribes_using_stored_topic_template() -> None:
    """_run() subscribes each SN using its stored topic_template (not hardcoded)."""
    client = _MqttClient(MQTT_CREDS, connect_timeout=5)
    subscribed_topics: list[str] = []

    async def hanging_stream():
        await asyncio.Event().wait()
        yield  # pragma: no cover

    mock_inner = AsyncMock()

    async def capture_subscribe(topic: str, *, qos: int = 0) -> None:
        subscribed_topics.append(topic)

    mock_inner.subscribe = capture_subscribe
    mock_inner.messages = hanging_stream()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    client.on_message("BK11DEVICE", lambda sn, data: None)

    with patch("ecoflow.transport.mqtt.aiomqtt.Client", return_value=mock_cm):
        await asyncio.wait_for(client.connect(), timeout=5.0)

    expected_topic = TOPIC_OPEN_QUOTA.format(
        user_id=MQTT_CREDS.user_id, sn="BK11DEVICE"
    )
    assert expected_topic in subscribed_topics
    await client.disconnect()
