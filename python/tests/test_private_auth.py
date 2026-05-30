"""Tests for ecoflow.private.auth — email/password login returning PrivateCredentials."""  # noqa: E501

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.exceptions import EcoFlowAuthError
from ecoflow.private.auth import PrivateCredentials, login

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HAPPY_RESPONSE = {
    "code": "0",
    "data": {
        "certificateAccount": "mqtt_user",
        "certificatePassword": "mqtt_pass",
        "userId": "user123",
    },
}


def make_mock_httpx_cls(response_json: dict) -> MagicMock:
    """Return a mock for httpx.AsyncClient that yields a client posting given JSON."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_json

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_cls


# ---------------------------------------------------------------------------
# Test 1 — Happy path: returns PrivateCredentials with correct fields
# ---------------------------------------------------------------------------


async def test_login_returns_private_credentials_with_correct_fields() -> None:
    """login() returns PrivateCredentials with all fields correctly mapped."""
    mock_cls = make_mock_httpx_cls(HAPPY_RESPONSE)
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
    mock_cls = make_mock_httpx_cls(HAPPY_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("test@example.com", "mypassword")

    mock_client = mock_cls.return_value.__aenter__.return_value
    call_args = mock_client.post.call_args
    url = call_args.args[0]
    assert "api.ecoflow.com/auth/login" in url


# ---------------------------------------------------------------------------
# Test 3 — Sends email and password as plain text JSON (no encoding)
# ---------------------------------------------------------------------------


async def test_login_sends_plain_text_credentials_in_json_body() -> None:
    """Email and password are sent as-is in the JSON body — no MD5 or base64."""
    mock_cls = make_mock_httpx_cls(HAPPY_RESPONSE)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        await login("user@example.com", "secret123")

    mock_client = mock_cls.return_value.__aenter__.return_value
    call_args = mock_client.post.call_args
    sent_json = call_args.kwargs.get("json")
    assert sent_json is not None
    assert sent_json["email"] == "user@example.com"
    assert sent_json["password"] == "secret123"  # plain text, not encoded


# ---------------------------------------------------------------------------
# Test 4 — Non-zero code raises EcoFlowAuthError with message text
# ---------------------------------------------------------------------------


async def test_login_raises_auth_error_on_non_zero_code() -> None:
    """Non-zero code raises EcoFlowAuthError containing the API's message."""
    error_response = {"code": "1", "message": "Invalid credentials"}
    mock_cls = make_mock_httpx_cls(error_response)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        with pytest.raises(EcoFlowAuthError, match="Invalid credentials"):
            await login("bad@example.com", "wrongpass")


# ---------------------------------------------------------------------------
# Test 5 — Integer code=0 is accepted as success
# ---------------------------------------------------------------------------


async def test_login_accepts_integer_zero_code_as_success() -> None:
    """An integer 0 code (not the string '0') is treated as success."""
    response_int_code = {
        "code": 0,  # integer, not string
        "data": {
            "certificateAccount": "acct",
            "certificatePassword": "pw",
            "userId": 99,  # also integer — must be coerced to str
        },
    }
    mock_cls = make_mock_httpx_cls(response_int_code)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        creds = await login("test@example.com", "password")

    assert creds.user_id == "99"  # coerced to string


# ---------------------------------------------------------------------------
# Test 6 — Missing 'data' key in response raises EcoFlowAuthError or KeyError
# ---------------------------------------------------------------------------


async def test_login_raises_on_missing_data_key() -> None:
    """If 'data' is absent from a success response, an error is raised."""
    response_no_data = {"code": "0"}  # code OK but no 'data' key
    mock_cls = make_mock_httpx_cls(response_no_data)
    with patch("ecoflow.private.auth.httpx.AsyncClient", mock_cls):
        with pytest.raises((EcoFlowAuthError, KeyError)):
            await login("test@example.com", "password")


# ---------------------------------------------------------------------------
# Test 7 — PrivateCredentials is frozen
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
