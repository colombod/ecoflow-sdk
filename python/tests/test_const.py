from ecoflow.const import (
    ECOFLOW_MQTT_HOST,
    ECOFLOW_MQTT_PORT_TLS,
    ECOFLOW_REST_HOST_EU,
    ECOFLOW_REST_HOST_US,
    ENDPOINT_CERT,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ENDPOINT_DEVICE_LIST,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    TOPIC_DEVICE_PROPERTY,
    TOPIC_OPEN_QUOTA,
    TOPIC_OPEN_STATUS,
    DeviceModel,
)


def test_rest_hosts() -> None:
    assert "ecoflow.com" in ECOFLOW_REST_HOST_EU
    assert "ecoflow.com" in ECOFLOW_REST_HOST_US
    assert ECOFLOW_REST_HOST_EU != ECOFLOW_REST_HOST_US


def test_mqtt_host_and_port() -> None:
    assert ECOFLOW_MQTT_HOST == "mqtt.ecoflow.com"
    assert ECOFLOW_MQTT_PORT_TLS == 8883


def test_topic_device_property_format() -> None:
    """Legacy topic still works and contains SN (backward compat)."""
    topic = TOPIC_DEVICE_PROPERTY.format(sn="SN12345")
    assert "SN12345" in topic


def test_topic_open_quota_format() -> None:
    """TOPIC_OPEN_QUOTA formats to the confirmed live-tested MQTT topic."""
    topic = TOPIC_OPEN_QUOTA.format(user_id="user456", sn="BK11DEVICE")
    assert topic == "/open/user456/BK11DEVICE/quota"


def test_topic_open_status_format() -> None:
    """TOPIC_OPEN_STATUS formats correctly with user_id and sn."""
    topic = TOPIC_OPEN_STATUS.format(user_id="user456", sn="BK11DEVICE")
    assert topic == "/open/user456/BK11DEVICE/status"


def test_device_model_enum_has_all_devices() -> None:
    assert DeviceModel.DELTA_PRO.value == "DELTA Pro"
    assert DeviceModel.SMART_PLUG.value == "Smart Plug"
    assert DeviceModel.WAVE_3.value == "Wave 3"
    assert DeviceModel.POWER_STREAM.value == "PowerStream"


def test_topic_open_set_format() -> None:
    """TOPIC_OPEN_SET formats to the correct command topic for the public API."""
    from ecoflow.const import TOPIC_OPEN_SET

    topic = TOPIC_OPEN_SET.format(user_id="user456", sn="BK11DEVICE")
    assert topic == "/open/user456/BK11DEVICE/set"


def test_topic_open_set_reply_format() -> None:
    """TOPIC_OPEN_SET_REPLY formats to the correct ACK topic."""
    from ecoflow.const import TOPIC_OPEN_SET_REPLY

    topic = TOPIC_OPEN_SET_REPLY.format(user_id="user456", sn="BK11DEVICE")
    assert topic == "/open/user456/BK11DEVICE/set_reply"
