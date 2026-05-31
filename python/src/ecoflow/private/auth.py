"""EcoFlow private API authentication — email/password login."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ecoflow.exceptions import EcoFlowAuthError

_LOGGER = logging.getLogger(__name__)
_LOGIN_URL = "https://api.ecoflow.com/auth/login"
_CERT_URL = "https://api.ecoflow.com/iot-auth/app/certification"
_TIMEOUT = 30.0


@dataclass(frozen=True)
class PrivateCredentials:
    """MQTT credentials obtained from the private EcoFlow login API."""

    certificate_account: str  # MQTT username
    certificate_password: str  # MQTT password
    user_id: str  # used in MQTT client_id construction


async def login(email: str, password: str) -> PrivateCredentials:
    """Authenticate with EcoFlow private API using app email and password.

    Two-step flow matching tolwi/hassio-ecoflow-cloud implementation:
    1. POST /auth/login with base64-encoded password → token + userId
    2. GET  /iot-auth/app/certification with Bearer token + userId body → MQTT creds

    QUIRK: Password must be base64-encoded before sending — NOT plain text.
    QUIRK: scene="IOT_APP" and userType="ECOFLOW" are required in the login body.
    QUIRK: userId must be sent as form-encoded body in the GET certification call.
    Source: tolwi/hassio-ecoflow-cloud private_api.py (MIT licence).

    Args:
        email: EcoFlow account email address.
        password: EcoFlow account password (will be base64-encoded before sending).

    Returns:
        PrivateCredentials with MQTT connection details.

    Raises:
        EcoFlowAuthError: if the API returns a non-zero code or required
            fields are missing from the response.
    """
    b64_password = base64.b64encode(password.encode()).decode()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # Step 1: Login → get token + userId
        login_resp = await client.post(
            _LOGIN_URL,
            json={
                "email": email,
                "password": b64_password,
                "scene": "IOT_APP",
                "userType": "ECOFLOW",
            },
            headers={"lang": "en_US", "content-type": "application/json"},
        )
        login_body: dict[str, Any] = login_resp.json()

        if str(login_body.get("code", "-1")) != "0":
            raise EcoFlowAuthError(
                f"EcoFlow login failed: {login_body.get('message', 'unknown error')}"
            )

        try:
            login_data: dict[str, Any] = login_body["data"]
            token = str(login_data["token"])
            user_id = str(login_data["user"]["userId"])
        except KeyError as exc:
            raise EcoFlowAuthError(f"missing field in login response: {exc}") from exc

        _LOGGER.debug("Logged in as user_id=%s", user_id)

        # Step 2: Get MQTT credentials using the token.
        # QUIRK: EcoFlow cert endpoint expects userId in the GET body (form-encoded),
        # matching the aiohttp data= pattern from tolwi/hassio-ecoflow-cloud.
        # httpx.AsyncClient.get() does not accept a body; use .request() instead.
        cert_resp = await client.request(
            "GET",
            _CERT_URL,
            data={"userId": user_id},
            headers={
                "lang": "en_US",
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
            },
        )
        cert_body: dict[str, Any] = cert_resp.json()

        if str(cert_body.get("code", "-1")) != "0":
            msg = cert_body.get("message", "unknown error")
            raise EcoFlowAuthError(f"MQTT certification failed: {msg}")

        try:
            cert_data: dict[str, Any] = cert_body["data"]
            return PrivateCredentials(
                certificate_account=str(cert_data["certificateAccount"]),
                certificate_password=str(cert_data["certificatePassword"]),
                user_id=user_id,
            )
        except KeyError as exc:
            raise EcoFlowAuthError(
                f"missing field in certification response: {exc}"
            ) from exc
