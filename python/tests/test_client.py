from unittest.mock import AsyncMock, patch

import respx
from httpx import Response

from ecoflow.auth import EcoFlowCredentials
from ecoflow.client import EcoFlowClient
from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.transport.mqtt import MqttCredentials

CREDS = EcoFlowCredentials(access_key="key", secret_key="secret")


async def test_client_can_be_constructed() -> None:
    client = EcoFlowClient(access_key="key", secret_key="secret", region="EU")
    assert client is not None


async def test_client_collections_empty_before_connect() -> None:
    client = EcoFlowClient(access_key="key", secret_key="secret", region="EU")
    assert client.batteries == []
    assert client.plugs == []
    assert client.meters == []
    assert client.wave3_units == []
    assert client.inverters == []
    assert client.unknown_devices == []


async def test_client_is_async_context_manager() -> None:
    client = EcoFlowClient(access_key="key", secret_key="secret", region="EU")
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    async with client:
        client.connect.assert_called_once()
    client.disconnect.assert_called_once()


@respx.mock
async def test_discover_populates_plugs() -> None:
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": [
                    {"sn": "SP001", "productName": "Smart Plug", "online": 1},
                    {"sn": "DP001", "productName": "DELTA Pro", "online": 1},
                ],
            },
        )
    )
    respx.get("https://api-e.ecoflow.com/iot-open/sign/certification").mock(
        return_value=Response(200, json={"code": 0, "data": {}})
    )
    client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
    with patch.object(client, "_mqtt", None):
        await client._discover()  # pyright: ignore[reportPrivateUsage]
    assert len(client.plugs) == 1
    assert client.plugs[0].sn == "SP001"
    assert len(client.batteries) == 1
    assert client.batteries[0].sn == "DP001"
    assert len(client.unknown_devices) == 0


@respx.mock
async def test_discover_unknown_device_not_dropped() -> None:
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": [
                    {
                        "sn": "XYZ001",
                        "productName": "Future Device Pro Max",
                        "online": 1,
                    },
                ],
            },
        )
    )
    client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
    with patch.object(client, "_mqtt", None):
        await client._discover()  # pyright: ignore[reportPrivateUsage]
    assert len(client.unknown_devices) == 1
    assert client.unknown_devices[0].product_name == "Future Device Pro Max"
    assert client.unknown_devices[0].raw["sn"] == "XYZ001"


@respx.mock
async def test_connect_uses_certificate_account_as_mqtt_user_id() -> None:
    """connect() must use certificateAccount (not userId) as the MQTT user_id.

    The EcoFlow certification API does NOT return a `userId` field; it returns
    `certificateAccount`.  Using the wrong key produces an empty string, making
    the topic `/open//{sn}/quota` instead of `/open/{account}/{sn}/quota` and
    causing zero MQTT events to be received.
    """
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(200, json={"code": 0, "data": []})
    )
    respx.get("https://api-e.ecoflow.com/iot-open/sign/certification").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "certificateAccount": "open-b4b306eddfae4e8f8667f7281b994077",
                    "certificatePassword": "s3cr3t",
                    "url": "mqtt.ecoflow.com",
                    "port": "8883",
                    "protocol": "mqtts",
                    # NOTE: no `userId` field — matches real API response
                },
            },
        )
    )
    captured_creds: list[MqttCredentials] = []

    async def fake_mqtt_connect(self) -> None:  # type: ignore[override]
        pass

    def _capture_side_effect(creds: MqttCredentials) -> AsyncMock:
        captured_creds.append(creds)
        return AsyncMock(connect=AsyncMock(), on_message=AsyncMock())

    with patch("ecoflow.client.MqttTransport", side_effect=_capture_side_effect):
        client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
        await client.connect()

    assert len(captured_creds) == 1, "MqttCredentials should have been constructed"
    assert captured_creds[0].user_id == "open-b4b306eddfae4e8f8667f7281b994077", (
        f"user_id must come from certificateAccount, got: {captured_creds[0].user_id!r}"
    )


@respx.mock
async def test_connect_registers_callbacks_before_mqtt_connect() -> None:
    """Device callbacks must be registered before MQTT connect(), not after.

    The EcoFlow broker sends an initial full-state dump on first subscription.
    If on_message() is called after connect(), _run() subscribes to an empty
    _subscriptions dict and misses the initial dump entirely.
    """
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": [
                    {"sn": "SP001", "productName": "Smart Plug", "online": 1},
                ],
            },
        )
    )
    respx.get("https://api-e.ecoflow.com/iot-open/sign/certification").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "certificateAccount": "open-testuser",
                    "certificatePassword": "s3cr3t",
                    "url": "mqtt.ecoflow.com",
                    "port": "8883",
                    "protocol": "mqtts",
                },
            },
        )
    )

    call_order: list[str] = []

    class FakeMqttClient:
        def __init__(self, creds: object) -> None:
            pass

        def on_message(self, sn: str, cb: object, **kwargs: object) -> None:
            call_order.append(f"on_message:{sn}")

        async def connect(self) -> None:
            call_order.append("connect")

        async def disconnect(self) -> None:
            pass

    with patch("ecoflow.client.MqttTransport", FakeMqttClient):
        client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
        await client.connect()

    assert "on_message:SP001" in call_order, f"on_message not called: {call_order}"
    assert "connect" in call_order, f"connect not called: {call_order}"
    on_message_idx = call_order.index("on_message:SP001")
    connect_idx = call_order.index("connect")
    assert on_message_idx < connect_idx, (
        f"on_message must be called BEFORE connect, but got order: {call_order}"
    )


async def test_global_events_yields_from_mqtt_subscriptions() -> None:
    """The global event stream yields events from all device subscriptions."""
    client = EcoFlowClient(access_key="k", secret_key="s", region="EU")

    mock_rest = AsyncMock()
    mock_rest.get_quota = AsyncMock(
        return_value={"plug_heartbeat": {"plugState": 1, "watts": 50}}
    )
    plug = SmartPlugDevice(sn="SP001", product_name="Smart Plug", rest=mock_rest)
    client.plugs = [plug]
    client._all_typed = [plug]  # pyright: ignore[reportPrivateUsage]

    plug._handle_message("SP001", {"plug_heartbeat": {"plugState": 1, "watts": 50}})  # pyright: ignore[reportPrivateUsage]

    assert plug.data is not None
    assert plug.data.is_on is True
