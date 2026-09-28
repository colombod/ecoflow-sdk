"""EcoFlow's REST signature rule, written from the spec (never imports ecoflow.auth).

``HMAC-SHA256("<sorted k=v params>&accessKey=..&nonce=..&timestamp=..", secret)``.
Keeping this independent of the SDK's signer is what lets the twin catch a
signing regression in the SDK.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, cast


def _flatten(prefix: str, value: Any, out: dict[str, str]) -> None:  # noqa: ANN401
    if isinstance(value, dict):
        for k, v in cast(dict[str, Any], value).items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(value, list):
        for i, v in enumerate(cast(list[Any], value)):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out[prefix] = "true" if value else "false"
    else:
        out[prefix] = str(value)


def signed_params(
    query: Mapping[str, str], content_type: str, body: bytes
) -> dict[str, str]:
    """The params EcoFlow signs.

    The query string — unless the request declares ``Content-Type:
    application/json``, when the API signs the flattened JSON body instead
    (nothing, for a GET). Verified live 2026-09-27: a param-signed GET carrying
    that header is rejected with 8521. Raises ``ValueError`` on a bad body.
    """
    if "application/json" not in content_type.lower():
        return dict(query)
    params: dict[str, str] = {}
    if body:
        _flatten("", json.loads(body), params)
    return params


def signature(
    params: Mapping[str, str],
    access_key: str,
    nonce: str,
    timestamp: str,
    secret_key: str,
) -> str:
    auth = f"accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
    prefix = "&".join(f"{k}={params[k]}" for k in sorted(params))
    canonical = f"{prefix}&{auth}" if prefix else auth
    return hmac.new(secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
