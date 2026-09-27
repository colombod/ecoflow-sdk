"""EcoFlow REST authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class EcoFlowCredentials:
    """Official Developer API credentials from developer.ecoflow.com."""

    access_key: str
    secret_key: str


def _flatten(prefix: str, value: Any, out: dict[str, str]) -> None:  # noqa: ANN401
    if isinstance(value, Mapping):
        for k, v in cast(Mapping[str, Any], value).items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(value, list | tuple):
        for i, v in enumerate(cast(list[Any], value)):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out[prefix] = "true" if value else "false"
    else:
        out[prefix] = str(value)


def canonical_params(params: Mapping[str, Any] | None) -> str:
    """Flatten and sort request parameters into EcoFlow's signing format.

    Nested objects become ``a.b``, list items ``a[0]``; keys are sorted by
    ASCII and joined as ``k=v`` with ``&``.  For example
    ``{"sn": "X", "params": {"id": 1}}`` → ``"params.id=1&sn=X"``.
    """
    if not params:
        return ""
    flat: dict[str, str] = {}
    _flatten("", params, flat)
    return "&".join(f"{k}={flat[k]}" for k in sorted(flat))


def build_auth_headers(
    credentials: EcoFlowCredentials,
    params: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """
    Build the four signed headers required on every EcoFlow REST request.

    Signature algorithm (EcoFlow Developer API):
      canonical = "{sorted request params}&accessKey={k}&nonce={n}&timestamp={ts}"
      sign      = HMAC-SHA256(canonical, secret_key) — hex encoded

    *params* are the query parameters (GET) or JSON body (PUT/POST); they
    must be part of the signed string or the API rejects the request with
    "signature is wrong".  With no params the prefix is omitted.
    """
    timestamp = str(int(time.time() * 1000))
    nonce = str(secrets.randbelow(900_000) + 100_000)
    canonical = (
        f"accessKey={credentials.access_key}&nonce={nonce}&timestamp={timestamp}"
    )
    prefix = canonical_params(params)
    if prefix:
        canonical = f"{prefix}&{canonical}"
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
