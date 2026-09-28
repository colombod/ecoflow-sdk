"""Endpoints: point the SDK at EcoFlow's cloud (default) or a digital twin."""

from __future__ import annotations

import ssl
from unittest.mock import MagicMock, patch

import pytest
import respx
from httpx import Response

from ecoflow.auth import EcoFlowCredentials
from ecoflow.client import EcoFlowClient
from ecoflow.endpoints import ENV_CA_FILE, ENV_REST_BASE, Endpoints
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from ecoflow.transport.rest import RestTransport

CREDS = EcoFlowCredentials("k", "s")


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://127.0.0.1:8443")
    monkeypatch.setenv(ENV_CA_FILE, "/tmp/ca.pem")
    assert Endpoints.from_env() == Endpoints("https://127.0.0.1:8443", "/tmp/ca.pem")


def test_from_env_unset_means_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_REST_BASE, raising=False)
    monkeypatch.delenv(ENV_CA_FILE, raising=False)
    assert Endpoints.from_env() == Endpoints()


def test_ssl_context_defaults_to_system_trust() -> None:
    ctx = Endpoints().ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


@respx.mock
async def test_rest_base_overrides_region_host() -> None:
    route = respx.get("https://twin.test/iot-open/sign/device/list").mock(
        return_value=Response(200, json={"code": "0", "data": []})
    )
    async with RestTransport(
        CREDS, region="EU", endpoints=Endpoints(rest_base="https://twin.test")
    ) as rest:
        assert await rest.list_devices() == []
    assert route.called


async def test_mqtt_transport_uses_given_ssl_context() -> None:
    ctx = ssl.create_default_context()
    creds = MqttCredentials("h", 8883, "mqtts", "u", "p", "c", "acct")
    client_cls = MagicMock(side_effect=RuntimeError("stop"))
    transport = MqttTransport(creds, connect_timeout=0.2, ssl_context=ctx)
    with patch("ecoflow.transport.mqtt.aiomqtt.Client", client_cls):
        with pytest.raises(
            EcoFlowConnectionError
        ):  # times out after the stubbed failure
            await transport.connect()
    assert client_cls.call_args.kwargs["tls_context"] is ctx


def test_client_reads_env_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://twin.test")
    client = EcoFlowClient("k", "s")
    assert client.endpoints.rest_base == "https://twin.test"


def test_explicit_endpoints_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://from-env.test")
    client = EcoFlowClient("k", "s", endpoints=Endpoints())
    assert client.endpoints.rest_base is None
