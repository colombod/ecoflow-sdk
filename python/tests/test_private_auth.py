"""Tests for ecoflow.private.auth — email/password login returning PrivateCredentials."""  # noqa: E501

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.exceptions import EcoFlowAuthError
from ecoflow.private.auth import PrivateCredentials, login

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOGIN_RESPONSE = {
    "code": "0",
    "data": {
        "token": "test_token_abc123",
        "user": {
            "userId": "user123",
        },
    },
}

CERT_RESPONSE = {
    "code": "0",
    "data": {
        "certificateAccount": "mqtt_user",
        "certificatePassword": "mqtt_pass",
        "url": "mqtt.ecoflow.com",
        "port": "8883",
    },
}


def make_mock_httpx_cls(
    login_json: dict[str, Any],
    cert_json: dict[str, Any] | None = None,
) -> MagicMock:
    """Return a mock for httpx.AsyncClient that yields a client with post/get mocked.

    If cert_json is None, defaults to CERT_RESPONSE.
    """
    if cert_json is None:
        cert_json = CERT_RESPONSE

    login_resp = MagicMock()
    login_resp.json.return_value = login_json

    cert_resp = MagicMock()
    cert_resp.json.return_value = cert_json

    mock_client = AsyncMock()
    mock_client.post.return_value = login_resp
    mock_client.get.return_value = cert_resp

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_cls


# ---------------------------------------------------------------------------
# Test 1 — Happy path: returns PrivateCredentials with correct fields
# ---------------------------------------------------------------------------


async def test_login_returns_private_credentials_with_correct_fields() -> None:
    """login() returns PrivateCredentials with all fields correctly mapped."""
    mock_cls = make_mock_httpx_cls(LOGIN_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        creds = await login("test@example.com", "mypassword")

    assert isinstance(creds, PrivateCredentials)
    assert creds.certificate_account == "mqtt_user"
    assert creds.certificate_password == "mqtt_pass"
    assert creds.user_id == "user123"


# ---------------------------------------------------------------------------
# Test 2 — POSTs to URL containing 'api.ecoflow.com/auth/login'
# ---------------------------------------------------------------------------


async def test_login_posts_to_correct_url() -> None:
    """POST is made to the EcoFlow private auth endpoint."""
    mock_cls = make_mock_httpx_cls(LOGIN_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("test@example.com", "mypassword")

    mock_client = mock_cls.return_value.__aenter__.return_value
    call_args = mock_client.post.call_args
    url = call_args.args[0]
    assert "api.ecoflow.com/auth/login" in url


# ---------------------------------------------------------------------------
# Test 3 — Sends email and base64-encoded password in JSON body
# ---------------------------------------------------------------------------


async def test_login_sends_base64_encoded_password_in_json_body() -> None:
    """Email is sent as-is; password is base64-encoded before sending."""
    mock_cls = make_mock_httpx_cls(LOGIN_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("user@example.com", "secret123")

    mock_client = mock_cls.return_value.__aenter__.return_value
    call_args = mock_client.post.call_args
    sent_json = call_args.kwargs.get("json")
    expected_b64 = base64.b64encode(b"secret123").decode()
    assert sent_json is not None
    assert sent_json["email"] == "user@example.com"
    assert sent_json["password"] == expected_b64  # base64-encoded, not plain text


# ---------------------------------------------------------------------------
# Test 4 — Sends required extra fields: scene and userType
# ---------------------------------------------------------------------------


async def test_login_sends_scene_and_user_type() -> None:
    """scene='IOT_APP' and userType='ECOFLOW' are included in the JSON body."""
    mock_cls = make_mock_httpx_cls(LOGIN_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("user@example.com", "secret123")

    mock_client = mock_cls.return_value.__aenter__.return_value
    call_args = mock_client.post.call_args
    sent_json = call_args.kwargs.get("json")
    assert sent_json is not None
    assert sent_json["scene"] == "IOT_APP"
    assert sent_json["userType"] == "ECOFLOW"


# ---------------------------------------------------------------------------
# Test 5 — Non-zero code raises EcoFlowAuthError with message text
# ---------------------------------------------------------------------------


async def test_login_raises_auth_error_on_non_zero_code() -> None:
    """Non-zero code raises EcoFlowAuthError containing the API's message."""
    error_response = {"code": "1", "message": "Invalid credentials"}
    mock_cls = make_mock_httpx_cls(error_response)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        with pytest.raises(EcoFlowAuthError, match="Invalid credentials"):
            await login("bad@example.com", "wrongpass")


# ---------------------------------------------------------------------------
# Test 6 — Makes two HTTP calls: POST login, then GET certification
# ---------------------------------------------------------------------------


async def test_login_makes_two_http_calls() -> None:
    """login() makes POST to /auth/login and GET to /iot-auth/app/certification."""
    mock_cls = make_mock_httpx_cls(LOGIN_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("user@example.com", "secret123")

    mock_client = mock_cls.return_value.__aenter__.return_value
    assert mock_client.post.call_count == 1, "Expected one POST call"
    assert mock_client.get.call_count == 1, "Expected one GET call (certification)"

    post_url = mock_client.post.call_args.args[0]
    get_url = mock_client.get.call_args.args[0]
    assert "auth/login" in post_url
    assert "iot-auth/app/certification" in get_url


# ---------------------------------------------------------------------------
# Test 7 — Bearer token from login is forwarded to certification call
# ---------------------------------------------------------------------------


async def test_login_forwards_token_to_certification_call() -> None:
    """The token from the login response is sent as Bearer in the cert call."""
    mock_cls = make_mock_httpx_cls(LOGIN_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("user@example.com", "secret123")

    mock_client = mock_cls.return_value.__aenter__.return_value
    get_call = mock_client.get.call_args
    headers = get_call.kwargs.get("headers", {})
    assert "authorization" in headers
    assert headers["authorization"] == "Bearer test_token_abc123"


# ---------------------------------------------------------------------------
# Test 8 — Integer code=0 is accepted as success
# ---------------------------------------------------------------------------


async def test_login_accepts_integer_zero_code_as_success() -> None:
    """An integer 0 code (not the string '0') is treated as success."""
    response_int_code = {
        "code": 0,  # integer, not string
        "data": {
            "token": "tok",
            "user": {"userId": 99},  # also integer — must be coerced to str
        },
    }
    mock_cls = make_mock_httpx_cls(response_int_code)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        creds = await login("test@example.com", "password")

    assert creds.user_id == "99"  # coerced to string


# ---------------------------------------------------------------------------
# Test 9 — PrivateCredentials is frozen
# ---------------------------------------------------------------------------


def test_private_credentials_is_frozen() -> None:
    """Assigning to any field of PrivateCredentials raises AttributeError or TypeError."""  # noqa: E501
    creds = PrivateCredentials(
        certificate_account="user",
        certificate_password="pass",
        user_id="123",
    )
    with pytest.raises((AttributeError, TypeError)):
        creds.user_id = "new_id"  # type: ignore[misc]
