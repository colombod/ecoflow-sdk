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


def test_env_override_is_logged_as_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://twin.test")
    monkeypatch.delenv(ENV_CA_FILE, raising=False)
    with caplog.at_level("WARNING", logger="ecoflow.endpoints"):
        Endpoints.from_env()
    assert "https://twin.test" in caplog.text and "access key" in caplog.text


def test_no_warning_without_override(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(ENV_REST_BASE, raising=False)
    monkeypatch.delenv(ENV_CA_FILE, raising=False)
    with caplog.at_level("WARNING", logger="ecoflow.endpoints"):
        Endpoints.from_env()
    assert caplog.text == ""


@pytest.mark.parametrize(
    "base",
    [
        "http://twin.test",
        "twin.test",
        "ftp://twin.test",
        "https:foo",
        "https://",
        "https:///x",
    ],
)
def test_rest_base_must_be_https(base: str) -> None:
    with pytest.raises(ValueError, match="https"):
        Endpoints(rest_base=base)


def test_ca_only_override_warns_about_trust_not_host(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Only the trusted CA changes; requests still go to EcoFlow."""
    monkeypatch.delenv(ENV_REST_BASE, raising=False)
    monkeypatch.setenv(ENV_CA_FILE, "/tmp/twin-ca.pem")
    with caplog.at_level("WARNING", logger="ecoflow.endpoints"):
        Endpoints.from_env()
    assert "/tmp/twin-ca.pem" in caplog.text and "trust" in caplog.text
    assert "access key" not in caplog.text


def test_accepts_https_host_with_port() -> None:
    assert Endpoints(rest_base="https://127.0.0.1:8443").rest_base


@pytest.mark.parametrize(
    "base",
    [
        "https://twin.test:abc",
        "https://twin.test:65536",
        "https://twin.test:-1",
        "https://twin.test:8443:9",
        "https://[::1",
    ],
)
def test_rest_base_rejects_malformed_url(base: str) -> None:
    with pytest.raises(ValueError, match="not a valid URL"):
        Endpoints(rest_base=base)


def test_rest_base_rejects_port_zero() -> None:
    with pytest.raises(ValueError, match="port"):
        Endpoints(rest_base="https://twin.test:0")


def test_rest_base_rejects_whitespace_in_host() -> None:
    with pytest.raises(ValueError, match="https"):
        Endpoints(rest_base="https:// twin.test")


@pytest.mark.parametrize("base", ["https://twin.test?x=1", "https://twin.test#frag"])
def test_rest_base_rejects_query_and_fragment(base: str) -> None:
    with pytest.raises(ValueError, match="query or fragment"):
        Endpoints(rest_base=base)


def test_rest_base_accepts_a_path_prefix() -> None:
    assert Endpoints(rest_base="https://twin.test:8443/base/").rest_origin == (
        "https://twin.test:8443"
    )


@pytest.mark.parametrize(
    "base", ["https://user:hunter2@twin.test", "https://token@twin.test"]
)
def test_rest_base_rejects_credentials_without_echoing_them(base: str) -> None:
    with pytest.raises(ValueError, match="credentials") as info:
        Endpoints(rest_base=base)
    assert "hunter2" not in str(info.value) and "token" not in str(info.value)


def test_override_warning_logs_only_the_origin(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A path may carry a secret; the warning names only scheme://host:port."""
    monkeypatch.setenv(ENV_REST_BASE, "https://twin.test:8443/base/secret-token/")
    monkeypatch.delenv(ENV_CA_FILE, raising=False)
    with caplog.at_level("WARNING", logger="ecoflow.endpoints"):
        Endpoints.from_env()
    assert "https://twin.test:8443" in caplog.text
    assert "secret" not in caplog.text and "/base" not in caplog.text


def test_rest_origin_brackets_ipv6() -> None:
    assert (
        Endpoints(rest_base="https://[::1]:8443/x").rest_origin == "https://[::1]:8443"
    )
