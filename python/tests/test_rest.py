"""Tests for the private _RestClient REST transport."""

import pytest
import respx
from httpx import Response

from ecoflow.auth import EcoFlowCredentials
from ecoflow.exceptions import (
    EcoFlowAuthError,
    EcoFlowDeviceNotFoundError,
    EcoFlowError,
)
from ecoflow.transport.rest import _RestClient

CREDS = EcoFlowCredentials(access_key="test_key", secret_key="test_secret")
BASE = "https://api-e.ecoflow.com"


@respx.mock
async def test_list_devices_returns_list() -> None:
    respx.get(f"{BASE}/iot-open/sign/device/list").mock(
        return_value=Response(
            200,
            json={
                "code": "0",
                "data": [{"sn": "SP12345", "productName": "Smart Plug", "online": 1}],
            },
        )
    )
    async with _RestClient(CREDS, region="EU") as client:
        devices = await client.list_devices()
    assert len(devices) == 1
    assert devices[0]["sn"] == "SP12345"


@respx.mock
async def test_list_devices_raises_auth_error_on_401() -> None:
    respx.get(f"{BASE}/iot-open/sign/device/list").mock(
        return_value=Response(401, json={"code": 400, "message": "Unauthorized"})
    )
    async with _RestClient(CREDS, region="EU") as client:
        with pytest.raises(EcoFlowAuthError):
            await client.list_devices()


@respx.mock
async def test_get_device_returns_device() -> None:
    sn = "EB12345"
    respx.get(f"{BASE}/iot-open/sign/device/{sn}").mock(
        return_value=Response(
            200,
            json={
                "code": "0",
                "data": {"sn": sn, "productName": "DELTA 2", "online": 1},
            },
        )
    )
    async with _RestClient(CREDS, region="EU") as client:
        device = await client.get_device(sn)
    assert device["sn"] == sn


@respx.mock
async def test_get_device_raises_device_not_found_when_empty() -> None:
    sn = "NOTFOUND"
    respx.get(f"{BASE}/iot-open/sign/device/{sn}").mock(
        return_value=Response(200, json={"code": "0", "data": {}})
    )
    async with _RestClient(CREDS, region="EU") as client:
        with pytest.raises(EcoFlowDeviceNotFoundError):
            await client.get_device(sn)


@respx.mock
async def test_get_quota_returns_data() -> None:
    sn = "EB12345"
    respx.get(f"{BASE}/iot-open/sign/device/quota/all").mock(
        return_value=Response(200, json={"code": "0", "data": {"soc": 80}})
    )
    async with _RestClient(CREDS, region="EU") as client:
        data = await client.get_quota(sn)
    assert data == {"soc": 80}


@respx.mock
async def test_set_quota_puts_payload() -> None:
    sn = "EB12345"
    respx.put(f"{BASE}/iot-open/sign/device/quota").mock(
        return_value=Response(200, json={"code": "0", "data": {}})
    )
    async with _RestClient(CREDS, region="EU") as client:
        result = await client.set_quota(sn, {"maxChargeSoc": 90})
    assert result == {}


@respx.mock
async def test_get_mqtt_credentials_returns_cert_data() -> None:
    respx.get(f"{BASE}/iot-open/sign/certification").mock(
        return_value=Response(
            200,
            json={
                "code": "0",
                "data": {
                    "url": "mqtt.ecoflow.com",
                    "port": "8883",
                    "clientId": "test_client",
                    "username": "user",
                    "password": "pass",
                },
            },
        )
    )
    async with _RestClient(CREDS, region="EU") as client:
        creds = await client.get_mqtt_credentials()
    assert creds["url"] == "mqtt.ecoflow.com"


@respx.mock
async def test_us_region_uses_us_host() -> None:
    us_base = "https://api.ecoflow.com"
    respx.get(f"{us_base}/iot-open/sign/device/list").mock(
        return_value=Response(200, json={"code": "0", "data": []})
    )
    async with _RestClient(CREDS, region="US") as client:
        devices = await client.list_devices()
    assert devices == []


@respx.mock
async def test_api_error_code_raises_ecoflow_error() -> None:
    respx.get(f"{BASE}/iot-open/sign/device/list").mock(
        return_value=Response(200, json={"code": 500, "message": "Internal error"})
    )
    async with _RestClient(CREDS, region="EU") as client:
        with pytest.raises(EcoFlowError):
            await client.list_devices()


@respx.mock
async def test_get_quota_passes_sn_param() -> None:
    respx.get(f"{BASE}/iot-open/sign/device/quota/all").mock(
        return_value=Response(200, json={"code": "0", "data": {"soc": 85}})
    )
    async with _RestClient(CREDS, region="EU") as client:
        data = await client.get_quota("SN99999")
    assert data["soc"] == 85


@respx.mock
async def test_set_quota_sends_put() -> None:
    route = respx.put(f"{BASE}/iot-open/sign/device/quota").mock(
        return_value=Response(200, json={"code": "0", "data": {}})
    )
    async with _RestClient(CREDS, region="EU") as client:
        await client.set_quota("SN99999", {"switch": 1})
    assert route.called


@respx.mock
async def test_get_mqtt_credentials_returns_dict() -> None:
    respx.get(f"{BASE}/iot-open/sign/certification").mock(
        return_value=Response(
            200,
            json={
                "code": "0",
                "data": {
                    "url": "mqtt.ecoflow.com",
                    "port": "8883",
                    "protocol": "mqtts",
                    "certificateAccount": "user123",
                    "certificatePassword": "pass123",
                    "clientId": "client123",
                    "userId": "user456",
                },
            },
        )
    )
    async with _RestClient(CREDS, region="EU") as client:
        data = await client.get_mqtt_credentials()
    assert data["url"] == "mqtt.ecoflow.com"


@respx.mock
async def test_api_error_raises_ecoflow_error() -> None:
    respx.get(f"{BASE}/iot-open/sign/device/list").mock(
        return_value=Response(200, json={"code": 500, "message": "Server error"})
    )
    async with _RestClient(CREDS, region="EU") as client:
        with pytest.raises(EcoFlowError):
            await client.list_devices()
