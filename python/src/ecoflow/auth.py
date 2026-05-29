"""EcoFlow REST authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class EcoFlowCredentials:
    """Official Developer API credentials from developer.ecoflow.com."""

    access_key: str
    secret_key: str


def build_auth_headers(credentials: EcoFlowCredentials) -> dict[str, str]:
    """
    Build the four signed headers required on every EcoFlow REST request.

    Signature algorithm:
      canonical = "accessKey={k}&nonce={n}&timestamp={ts}"
      sign      = HMAC-SHA256(canonical, secret_key) — hex encoded
    """
    timestamp = str(int(time.time() * 1000))
    nonce = str(secrets.randbelow(900_000) + 100_000)
    canonical = (
        f"accessKey={credentials.access_key}&nonce={nonce}&timestamp={timestamp}"
    )
    sign = hmac.new(
        credentials.secret_key.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "accessKey": credentials.access_key,
        "timestamp": timestamp,
        "nonce": nonce,
        "sign": sign,
    }
