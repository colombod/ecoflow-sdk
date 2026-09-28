from __future__ import annotations

import re
from pathlib import Path

import httpx

import ecoflow_twin.signing as signing_module
from ecoflow.auth import EcoFlowCredentials, build_auth_headers
from ecoflow_twin.signing import signature, signed_params

CREDS = EcoFlowCredentials("ak", "sk")


def _sdk_request(params: dict[str, str]) -> dict[str, str]:
    return build_auth_headers(CREDS, params)


def test_sdk_signed_query_verifies() -> None:
    h = _sdk_request({"sn": "X1"})
    params = signed_params({"sn": "X1"}, "", b"")
    assert signature(params, "ak", h["nonce"], h["timestamp"], "sk") == h["sign"]


def test_json_content_type_signs_body_not_query() -> None:
    """Live 2026-09-27: with this header a param-signed GET fails with 8521."""
    h = _sdk_request({"sn": "X1"})
    params = signed_params({"sn": "X1"}, "application/json", b"")
    assert signature(params, "ak", h["nonce"], h["timestamp"], "sk") != h["sign"]


def test_json_body_is_flattened_like_the_sdk() -> None:
    body = {"sn": "X1", "params": {"cfgRelay2Onoff": True, "list": [1, 2]}}
    h = build_auth_headers(CREDS, body)
    request = httpx.Request("PUT", "https://t/x", json=body)
    params = signed_params({}, "application/json", request.content)
    assert signature(params, "ak", h["nonce"], h["timestamp"], "sk") == h["sign"]


def test_independent_of_the_sdk_signer() -> None:
    source = Path(signing_module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+ecoflow\.auth", source, re.MULTILINE)
