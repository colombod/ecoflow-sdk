"""Tests for ecoflow.private.auth — email/password login returning PrivateCredentials.

Uses `respx` to mock httpx at the transport layer for precise request inspection.
"""

from __future__ import annotations

import base64
import json
import urllib.parse

import pytest
import respx

from ecoflow.exceptions import EcoFlowAuthError
from ecoflow.private.auth import PrivateCredentials, login

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOGIN_URL = "https://api.ecoflow.com/auth/login"
CERT_URL = "https://api.ecoflow.com/iot-auth/app/certification"

LOGIN_OK = {
    "code": "0",
    "data": {
        "token": "tok123",
        "user": {"userId": 42},
    },
}
CERT_OK = {
    "code": "0",
    "data": {
        "certificateAccount": "app-abc123",
        "certificatePassword": "certpass",
    },
}


# ---------------------------------------------------------------------------
# Test 1 — Happy path: returns PrivateCredentials with correct fields
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_success() -> None:
    """login() returns PrivateCredentials with all fields correctly mapped."""
    respx.post(LOGIN_URL).respond(json=LOGIN_OK)
    respx.get(CERT_URL).respond(json=CERT_OK)

    creds = await login("user@example.com", "mypassword")

    assert creds == PrivateCredentials(
        certificate_account="app-abc123",
        certificate_password="certpass",
        user_id="42",
    )


# ---------------------------------------------------------------------------
# Test 2 — Non-zero code raises EcoFlowAuthError
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_wrong_password_raises() -> None:
    """Non-zero code in login response raises EcoFlowAuthError."""
    respx.post(LOGIN_URL).respond(json={"code": "1000", "message": "wrong password"})

    with pytest.raises(EcoFlowAuthError):
        await login("user@example.com", "wrongpass")


# ---------------------------------------------------------------------------
# Test 3 — Password is base64-encoded in POST body
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_password_is_base64_encoded() -> None:
    """Password is base64-encoded before being sent — never plain text."""
    post_route = respx.post(LOGIN_URL).respond(json=LOGIN_OK)
    respx.get(CERT_URL).respond(json=CERT_OK)

    await login("user@example.com", "mypassword")

    body = json.loads(post_route.calls.last.request.content)
    expected_b64 = base64.b64encode(b"mypassword").decode()
    assert body["password"] == expected_b64


# ---------------------------------------------------------------------------
# Test 4 — scene and userType required fields are present in POST body
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_sends_required_fields() -> None:
    """scene='IOT_APP' and userType='ECOFLOW' are sent in the login POST body."""
    post_route = respx.post(LOGIN_URL).respond(json=LOGIN_OK)
    respx.get(CERT_URL).respond(json=CERT_OK)

    await login("user@example.com", "mypassword")

    body = json.loads(post_route.calls.last.request.content)
    assert body["scene"] == "IOT_APP"
    assert body["userType"] == "ECOFLOW"


# ---------------------------------------------------------------------------
# Test 5 — Two HTTP calls: POST to /auth/login, GET to /certification
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_makes_two_http_calls() -> None:
    """login() makes exactly one POST and one GET to the expected endpoints."""
    post_route = respx.post(LOGIN_URL).respond(json=LOGIN_OK)
    get_route = respx.get(CERT_URL).respond(json=CERT_OK)

    await login("user@example.com", "mypassword")

    assert post_route.call_count == 1, "Expected one POST to /auth/login"
    assert get_route.call_count == 1, "Expected one GET to /certification"


# ---------------------------------------------------------------------------
# Test 6 — Bearer token forwarded to certification call
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_forwards_bearer_token_to_cert_call() -> None:
    """Token from login response appears as 'Bearer <token>' in cert GET headers."""
    respx.post(LOGIN_URL).respond(json=LOGIN_OK)
    get_route = respx.get(CERT_URL).respond(json=CERT_OK)

    await login("user@example.com", "mypassword")

    headers = dict(get_route.calls.last.request.headers)
    assert headers.get("authorization") == "Bearer tok123"


# ---------------------------------------------------------------------------
# Test 7 — userId sent in cert GET request body (form-encoded)
# QUIRK: EcoFlow cert endpoint expects userId in GET body — not as query param.
# Source: tolwi/hassio-ecoflow-cloud private_api.py (aiohttp data={"userId": ...})
# ---------------------------------------------------------------------------


@respx.mock
async def test_cert_sends_user_id_in_request_body() -> None:
    """userId (from login) is sent in the cert GET body as form-encoded data."""
    respx.post(LOGIN_URL).respond(json=LOGIN_OK)
    get_route = respx.get(CERT_URL).respond(json=CERT_OK)

    await login("user@example.com", "mypassword")

    cert_request = get_route.calls.last.request
    body = dict(urllib.parse.parse_qsl(cert_request.content.decode()))
    assert body.get("userId") == "42", (
        f"Expected userId='42' in cert GET body; got body={body!r}. "
        "EcoFlow cert endpoint requires userId in form-encoded body."
    )


# ---------------------------------------------------------------------------
# Test 8 — Integer code=0 is accepted; userId coerced to string
# ---------------------------------------------------------------------------


@respx.mock
async def test_login_accepts_integer_zero_code_as_success() -> None:
    """Integer 0 code is accepted as success; integer userId is coerced to str."""
    login_int_code = {
        "code": 0,
        "data": {
            "token": "tok",
            "user": {"userId": 99},
        },
    }
    respx.post(LOGIN_URL).respond(json=login_int_code)
    respx.get(CERT_URL).respond(json=CERT_OK)

    creds = await login("test@example.com", "password")

    assert creds.user_id == "99"


# ---------------------------------------------------------------------------
# Test 9 — PrivateCredentials is frozen (immutable)
# ---------------------------------------------------------------------------


def test_private_credentials_is_frozen() -> None:
    """Assigning to any field of PrivateCredentials raises an error."""
    creds = PrivateCredentials(
        certificate_account="user",
        certificate_password="pass",
        user_id="123",
    )
    with pytest.raises((AttributeError, TypeError)):
        creds.user_id = "new_id"  # type: ignore[misc]
