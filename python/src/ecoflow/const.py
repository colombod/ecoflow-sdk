"""EcoFlow API constants."""

from enum import StrEnum

# REST API hosts
ECOFLOW_REST_HOST_EU = "https://api-e.ecoflow.com"
ECOFLOW_REST_HOST_US = "https://api.ecoflow.com"

# MQTT broker
ECOFLOW_MQTT_HOST = "mqtt.ecoflow.com"
ECOFLOW_MQTT_PORT_TLS = 8883
ECOFLOW_MQTT_KEEPALIVE = 60

# REST endpoints
ENDPOINT_DEVICE_LIST = "/iot-open/sign/device/list"
ENDPOINT_DEVICE_INFO = "/iot-open/sign/device/{sn}"
# GET — fetch all device properties
ENDPOINT_QUOTA_ALL = "/iot-open/sign/device/quota/all"
# PUT — set device properties
ENDPOINT_QUOTA_SET = "/iot-open/sign/device/quota"
ENDPOINT_CERT = "/iot-open/sign/certification"

# MQTT topic patterns — official Developer API (accessKey/secretKey)
# Confirmed by live testing: 36 events in 25 s on /open/ vs 0 on /app/device/property/
TOPIC_OPEN_QUOTA = "/open/{user_id}/{sn}/quota"
TOPIC_OPEN_STATUS = "/open/{user_id}/{sn}/status"

# Legacy topic — undocumented email/password API; kept for backward compat only
TOPIC_DEVICE_PROPERTY = "/app/device/property/{sn}"

# Command topics (unchanged)
TOPIC_DEVICE_SET = "/app/{user_id}/{sn}/thing/property/set"
TOPIC_DEVICE_GET = "/app/{user_id}/{sn}/thing/property/get"

# Timeouts
REST_TIMEOUT_S = 30
MQTT_CONNECT_TIMEOUT_S = 15

# Fallback device type routing by SN prefix when productName is absent.
# These prefixes are confirmed from real devices; add more as discovered.
SN_PREFIX_TO_MODEL: dict[str, str] = {
    "BK11": "STREAM Ultra",
    "BK21": "Smart Meter",
    "BK31": "STREAM AC Pro",
    "HW52": "Smart Plug",
}


class DeviceModel(StrEnum):
    """EcoFlow productName strings as returned by the device list API."""

    # Supported — full field mapping confirmed
    DELTA_PRO = "DELTA Pro"
    DELTA_PRO_3 = "DELTA Pro 3"
    DELTA_2 = "DELTA 2"
    DELTA_2_MAX = "DELTA 2 Max"
    RIVER_PRO = "RIVER PRO"
    RIVER_2 = "RIVER 2"
    RIVER_2_MAX = "RIVER 2 Max"
    RIVER_2_PRO = "RIVER 2 Pro"
    POWER_STREAM = "PowerStream"
    SMART_PLUG = "Smart Plug"
    SMART_METER = "Smart Meter"
    STREAM_ULTRA = "STREAM Ultra"
    STREAM_AC_PRO = "STREAM AC Pro"
    WAVE_3 = "Wave 3"
    # Partial — field mapping incomplete
    SMART_HOME_PANEL_2 = "Smart Home Panel 2"
    WAVE_2 = "Wave 2"
    SMART_GENERATOR = "Smart Generator"
