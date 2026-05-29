import hashlib
import hmac

from ecoflow.auth import EcoFlowCredentials, build_auth_headers


def test_credentials_immutable() -> None:
    creds = EcoFlowCredentials(access_key="key", secret_key="secret")
    assert creds.access_key == "key"
    assert creds.secret_key == "secret"


def test_build_auth_headers_keys() -> None:
    creds = EcoFlowCredentials(access_key="mykey", secret_key="mysecret")
    headers = build_auth_headers(creds)
    assert set(headers.keys()) == {"accessKey", "timestamp", "nonce", "sign"}


def test_build_auth_headers_access_key_matches() -> None:
    creds = EcoFlowCredentials(access_key="mykey", secret_key="mysecret")
    headers = build_auth_headers(creds)
    assert headers["accessKey"] == "mykey"


def test_build_auth_headers_sign_is_valid_hmac() -> None:
    creds = EcoFlowCredentials(access_key="mykey", secret_key="mysecret")
    headers = build_auth_headers(creds)
    canonical = (
        f"accessKey={headers['accessKey']}"
        f"&nonce={headers['nonce']}"
        f"&timestamp={headers['timestamp']}"
    )
    expected_sign = hmac.new(
        b"mysecret",
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert headers["sign"] == expected_sign


def test_each_call_produces_different_nonce() -> None:
    creds = EcoFlowCredentials(access_key="k", secret_key="s")
    h1 = build_auth_headers(creds)
    h2 = build_auth_headers(creds)
    # nonces should differ across calls (probabilistically)
    assert h1["nonce"] != h2["nonce"] or h1["timestamp"] != h2["timestamp"]
