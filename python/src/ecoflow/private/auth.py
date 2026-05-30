"""EcoFlow private API authentication — email/password login."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ecoflow.exceptions import EcoFlowAuthError

_LOGIN_URL = "https://api.ecoflow.com/auth/login"
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

    QUIRK: Password is sent as PLAIN TEXT in the JSON body (no MD5/base64).
    Confirmed from tolwi/hassio-ecoflow-cloud. If E2E returns auth error,
    check encoding and update this comment.

    Args:
        email: EcoFlow account email address.
        password: EcoFlow account password (sent verbatim).

    Returns:
        PrivateCredentials with MQTT connection details.

    Raises:
        EcoFlowAuthError: if the API returns a non-zero code or required
            fields are missing from the response.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            _LOGIN_URL,
            json={"email": email, "password": password},
            headers=_HEADERS,
        )
        body: dict[str, Any] = response.json()

    if str(body.get("code", "-1")) != "0":
        raise EcoFlowAuthError(str(body.get("message", "login failed")))

    try:
        data: dict[str, Any] = body["data"]
        return PrivateCredentials(
            certificate_account=str(data["certificateAccount"]),
            certificate_password=str(data["certificatePassword"]),
            user_id=str(data["userId"]),
        )
    except KeyError as exc:
        raise EcoFlowAuthError(f"missing field in login response: {exc}") from exc
