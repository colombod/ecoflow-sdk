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
                    "certificateAccount": "open-0123456789abcdef0123456789abcdef",
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

    def _capture_side_effect(creds: MqttCredentials, **_kwargs: object) -> AsyncMock:
        captured_creds.append(creds)
        return AsyncMock(connect=AsyncMock(), on_message=AsyncMock())

    with patch("ecoflow.client.MqttTransport", side_effect=_capture_side_effect):
        client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
        await client.connect()

    assert len(captured_creds) == 1, "MqttCredentials should have been constructed"
    assert captured_creds[0].user_id == "open-0123456789abcdef0123456789abcdef", (
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
        def __init__(self, creds: object, **_kwargs: object) -> None:
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


def test_mqtt_connected_returns_false_when_no_mqtt() -> None:
    client = EcoFlowClient(access_key="k", secret_key="s")
    assert client.mqtt_connected is False


def test_mqtt_subscriptions_returns_empty_when_no_mqtt() -> None:
    client = EcoFlowClient(access_key="k", secret_key="s")
    assert client.mqtt_subscriptions == frozenset()


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


@respx.mock
async def test_connect_injects_mqtt_into_devices() -> None:
    """Devices must have their _mqtt attribute set after connect().

    Bug: _discover() creates devices with mqtt=self._mqtt which is None at
    that point. After MqttTransport is created, devices still hold None and
    cannot publish commands (set_relay2, set_relay3, etc.) even though MQTT
    is live and delivering messages via callbacks.
    """
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": [
                    {
                        "sn": "BK11TESTSN000001",
                        "productName": "STREAM Ultra",
                        "online": 1,
                    },
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

    fake_mqtt_instance = AsyncMock()
    fake_mqtt_instance.connected = True
    fake_mqtt_instance.on_message = lambda sn, cb, **kw: None  # pyright: ignore[reportUnknownLambdaType]
    fake_mqtt_instance.connect = AsyncMock()
    fake_mqtt_instance.disconnect = AsyncMock()
    fake_mqtt_instance.creds = AsyncMock()
    fake_mqtt_instance.creds.user_id = "open-testuser"

    with patch("ecoflow.client.MqttTransport", return_value=fake_mqtt_instance):
        client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
        await client.connect()

    assert len(client.stream_units) == 1
    device = client.stream_units[0]

    # After connect(), the device's _mqtt must be the live transport — not None.
    # Without the fix, device._mqtt is None (set during _discover() before
    # MqttTransport was created) and set_relay2() raises EcoFlowConnectionError.
    assert device._mqtt is not None, (  # pyright: ignore[reportPrivateUsage]
        "device._mqtt is None after connect() — relay commands will always fail. "
        "Fix: backfill device._mqtt = self._mqtt after MqttTransport is created."
    )


@respx.mock
async def test_discover_matches_product_name_case_insensitively() -> None:
    """productName casing varies ("Delta Pro 3" vs "DELTA Pro 3")."""
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": [
                    {"sn": "MR51TEST", "productName": "Delta Pro 3", "online": 1},
                    {"sn": "HW52TEST", "productName": "smart plug", "online": 1},
                ],
            },
        )
    )
    client = EcoFlowClient(access_key="k", secret_key="s", region="EU")
    await client._discover()  # pyright: ignore[reportPrivateUsage]
    assert [b.sn for b in client.batteries] == ["MR51TEST"]
    assert [p.sn for p in client.plugs] == ["HW52TEST"]
    assert client.unknown_devices == []


@respx.mock
async def test_rest_only_mode_never_requests_mqtt_credentials() -> None:
    """enable_mqtt=False must not fetch certification or open MQTT."""
    respx.get("https://api-e.ecoflow.com/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={"code": 0, "data": [{"sn": "HW52TEST", "productName": "Smart Plug"}]},
        )
    )
    cert = respx.get("https://api-e.ecoflow.com/iot-open/sign/certification").mock(
        return_value=Response(200, json={"code": 0, "data": {}})
    )
    with patch("ecoflow.client.MqttTransport") as mqtt_cls:
        async with EcoFlowClient(
            access_key="k", secret_key="s", enable_mqtt=False
        ) as c:
            assert [p.sn for p in c.plugs] == ["HW52TEST"]
            assert c.mqtt_connected is False
    assert not cert.called
    mqtt_cls.assert_not_called()
