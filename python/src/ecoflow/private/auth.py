"""EcoFlow private API authentication — email/password login."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from ecoflow.exceptions import EcoFlowAuthError

_LOGIN_URL = "https://api.ecoflow.com/auth/login"
_CERT_URL = "https://api.ecoflow.com/iot-auth/app/certification"
_HEADERS = {"lang": "en_US", "country": "US"}
_TIMEOUT = 30.0


@dataclass(frozen=True)
class PrivateCredentials:
    """MQTT credentials obtained from the private EcoFlow login API."""

    certificate_account: str  # MQTT username
    certificate_password: str  # MQTT password
    user_id: str  # used in MQTT client_id construction


async def login(email: str, password: str) -> PrivateCredentials:
    """Authenticate with the private EcoFlow API using email and password.

    QUIRK: Password must be base64-encoded before sending (not MD5, not plain text).
    Confirmed from tolwi/hassio-ecoflow-cloud source (MIT licensed).
    Two-step auth: POST /auth/login → get token, then GET /iot-auth/app/certification
    → get MQTT credentials (certificateAccount, certificatePassword).

    Args:
        email: EcoFlow account email address.
        password: EcoFlow account password (will be base64-encoded before sending).

    Returns:
        PrivateCredentials with MQTT connection details.

    Raises:
        EcoFlowAuthError: if the API returns a non-zero code or required
            fields are missing from the response.
    """
    encoded_password = base64.b64encode(password.encode()).decode()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # Step 1: Login to get auth token
        login_response = await client.post(
            _LOGIN_URL,
            json={
                "email": email,
                "password": encoded_password,
                "scene": "IOT_APP",
                "userType": "ECOFLOW",
            },
            headers=_HEADERS,
        )
        login_body: dict[str, Any] = login_response.json()

        if str(login_body.get("code", "-1")) != "0":
            raise EcoFlowAuthError(str(login_body.get("message", "login failed")))

        try:
            login_data: dict[str, Any] = login_body["data"]
            token = str(login_data["token"])
            user_id = str(login_data["user"]["userId"])
        except KeyError as exc:
            raise EcoFlowAuthError(f"missing field in login response: {exc}") from exc

        # Step 2: Get MQTT certification credentials
        cert_response = await client.get(
            _CERT_URL,
            headers={**_HEADERS, "authorization": f"Bearer {token}"},
        )
        cert_body: dict[str, Any] = cert_response.json()

        if str(cert_body.get("code", "-1")) != "0":
            raise EcoFlowAuthError(
                str(cert_body.get("message", "certification failed"))
            )

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
