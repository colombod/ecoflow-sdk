# Wave 3 Private API — Phase 1: Foundation

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Build the proto schema, decoder, auth layer, and updated Wave3Status model needed to support Wave 3 devices via EcoFlow's private API.
**Architecture:** The `ecoflow.private` subpackage provides authentication and Protobuf decoding for Wave 3 devices. This phase creates every component except the MQTT connection class itself (Phase 2). All components are tested with unit tests — no real hardware or network credentials required.
**Tech Stack:** Python 3.11, httpx (already installed), protobuf>=4.0 (new optional dep), pytest, unittest.mock.

---

## Before you start

All commands run from `ecoflow-python/python/` (the directory containing `pyproject.toml`).
The virtual environment is managed by `uv`. Use `uv run pytest` not bare `pytest`.

Confirm you are in the right directory:
```bash
pwd   # should end in ecoflow-python/python
ls pyproject.toml   # should exist
```

---

### Task 1: Add protobuf to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Step 1: Edit `pyproject.toml`**

Find `[project.optional-dependencies]` and add the `wave3` group. Also add `protobuf>=4.0` to the existing `dev` group so tests work without `[wave3]`:

```toml
[project.optional-dependencies]
wave3 = ["protobuf>=4.0"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-timeout>=2.3",
    "respx>=0.21",
    "ruff>=0.6",
    "pyright>=1.1",
    "python-dotenv>=1.0",
    "protobuf>=4.0",
]
```

**Step 2: Sync the virtual environment**
```bash
uv sync
```
Expected: uv resolves and installs `protobuf`. No errors.

**Step 3: Verify protobuf installed**
```bash
uv run python -c "import google.protobuf; print(google.protobuf.__version__)"
```
Expected: prints a version string like `4.25.3` or `5.x.x`.

**Step 4: Commit**
```bash
git add pyproject.toml uv.lock
git commit -m "chore: add protobuf optional dep for wave3 private API"
```

---

### Task 2: Vendor `wave3_pb2.py` and create the private package skeleton

**Files:**
- Create: `src/ecoflow/private/__init__.py`
- Create: `src/ecoflow/private/proto/__init__.py`
- Create: `src/ecoflow/private/proto/wave3_pb2.py`  (vendored — do NOT modify)
- Create: `tests/test_private_proto.py`

**Step 1: Write the failing test**

Create `tests/test_private_proto.py`:

```python
"""Tests for vendored Wave 3 Protobuf schema."""

from __future__ import annotations


def test_wave3_proto_imports() -> None:
    """wave3_pb2 imports cleanly and exposes the expected message types."""
    from ecoflow.private.proto import wave3_pb2

    assert hasattr(wave3_pb2, "Wave3DisplayPropertyUpload"), (
        "wave3_pb2 must define Wave3DisplayPropertyUpload"
    )
    assert hasattr(wave3_pb2, "Wave3RuntimePropertyUpload"), (
        "wave3_pb2 must define Wave3RuntimePropertyUpload"
    )
    assert hasattr(wave3_pb2, "Wave3SetMessage"), (
        "wave3_pb2 must define Wave3SetMessage"
    )


def test_wave3_display_property_upload_instantiates() -> None:
    """Wave3DisplayPropertyUpload can be constructed and serialized."""
    from ecoflow.private.proto import wave3_pb2

    msg = wave3_pb2.Wave3DisplayPropertyUpload()
    raw = msg.SerializeToString()
    assert isinstance(raw, bytes)


def test_wave3_set_message_has_header() -> None:
    """Wave3SetMessage can be constructed with header fields."""
    from ecoflow.private.proto import wave3_pb2

    msg = wave3_pb2.Wave3SetMessage()
    msg.header.cmd_func = 254
    msg.header.cmd_id = 1
    assert msg.HasField("header")
```

**Step 2: Run the test — expect FAIL**
```bash
uv run pytest tests/test_private_proto.py -v
```
Expected: `ModuleNotFoundError: No module named 'ecoflow.private'`

**Step 3: Create the package skeleton**

Create `src/ecoflow/private/__init__.py` (minimal — Wave3Connection export comes in Phase 2):
```python
"""EcoFlow private API support (Wave 3, email/password authentication).

Install: pip install ecoflow-python[wave3]
"""
# Wave3Connection is exported here in Phase 2.
# This file intentionally left minimal for Phase 1.
```

Create `src/ecoflow/private/proto/__init__.py` (empty marker file):
```python
"""Protobuf schemas for EcoFlow private API."""
```

**Step 4: Download the vendored proto file**

Run this command to download `wave3_pb2.py` from the tolwi source:
```bash
curl -L -o src/ecoflow/private/proto/wave3_pb2.py \
  "https://raw.githubusercontent.com/tolwi/hassio-ecoflow-cloud/main/custom_components/ecoflow_cloud/devices/internal/proto/wave3_pb2.py"
```

**Step 5: Add the attribution comment to the top of `wave3_pb2.py`**

Open `src/ecoflow/private/proto/wave3_pb2.py`. Add these three lines at the very top, before any existing content:

```python
# Vendored from tolwi/hassio-ecoflow-cloud (MIT License)
# Source: https://github.com/tolwi/hassio-ecoflow-cloud
# Do not edit manually — regenerate from wave3.proto if updating.
```

**Step 6: Run the test — expect PASS**
```bash
uv run pytest tests/test_private_proto.py -v
```
Expected: all 3 tests PASS. If `Wave3RuntimePropertyUpload` does not exist in the downloaded file, remove that assertion from `test_wave3_proto_imports` (the file may only have the display upload type).

**Step 7: Commit**
```bash
git add src/ecoflow/private/ tests/test_private_proto.py
git commit -m "feat: vendor wave3_pb2 proto schema from tolwi/hassio-ecoflow-cloud (MIT)"
```

---

### Task 3: Implement `decoder.py` with unit tests

**Files:**
- Create: `src/ecoflow/private/proto/decoder.py`
- Create: `tests/test_private_decoder.py`

**Step 1: Write the failing tests**

Create `tests/test_private_decoder.py`:

```python
"""Unit tests for Wave 3 Protobuf decoder.

Tests the full decode() pipeline:
  - Error handling for empty / invalid bytes
  - XOR decryption logic (enc_type=1, src!=32)
  - Passthrough when enc_type=0 or src=32
  - cmd_func/cmd_id dispatch table
  - Field extraction from Wave3DisplayPropertyUpload
  - Per-mode param extraction from wave_mode_info
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers — build synthetic proto payloads without binary files
# ---------------------------------------------------------------------------


def _build_display_payload(
    fields: dict,
    enc_type: int = 0,
    src: int = 1,
    seq: int = 0,
    cmd_id: int = 1,
) -> bytes:
    """Construct a Wave3SetMessage wrapping a Wave3DisplayPropertyUpload.

    If enc_type=1 and src!=32, pdata is XOR-encrypted with (seq & 0xFF).
    This is the exact encoding used by the Wave 3 device firmware.
    """
    from ecoflow.private.proto import wave3_pb2

    inner = wave3_pb2.Wave3DisplayPropertyUpload()
    for k, v in fields.items():
        setattr(inner, k, v)
    inner_bytes = inner.SerializeToString()

    if enc_type == 1 and src != 32:
        key = seq & 0xFF
        inner_bytes = bytes(b ^ key for b in inner_bytes)

    msg = wave3_pb2.Wave3SetMessage()
    msg.header.cmd_func = 254
    msg.header.cmd_id = cmd_id
    msg.header.enc_type = enc_type
    msg.header.src = src
    msg.header.seq = seq
    msg.header.pdata = inner_bytes
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# Error-handling tests — no proto needed beyond import
# ---------------------------------------------------------------------------


def test_decode_empty_bytes_returns_empty_dict() -> None:
    """decode(b'') returns {} — never raises."""
    from ecoflow.private.proto.decoder import decode

    result = decode(b"")
    assert result == {}


def test_decode_garbage_bytes_returns_empty_dict() -> None:
    """decode() with invalid proto bytes returns {} — never raises."""
    from ecoflow.private.proto.decoder import decode

    result = decode(b"\xff\xfe\xfd\x00garbage data that is not protobuf")
    assert result == {}


def test_decode_message_without_header_returns_empty() -> None:
    """Wave3SetMessage with no header field yields {}."""
    from ecoflow.private.proto import wave3_pb2
    from ecoflow.private.proto.decoder import decode

    # Empty Wave3SetMessage serializes without setting header
    msg = wave3_pb2.Wave3SetMessage()
    result = decode(msg.SerializeToString())
    assert result == {}


# ---------------------------------------------------------------------------
# cmd_func / cmd_id dispatch tests
# ---------------------------------------------------------------------------


def test_decode_unknown_cmd_func_returns_empty() -> None:
    """cmd_func != 254 is ignored (ACKs, other subsystems)."""
    from ecoflow.private.proto import wave3_pb2
    from ecoflow.private.proto.decoder import decode

    msg = wave3_pb2.Wave3SetMessage()
    msg.header.cmd_func = 1   # not 254
    msg.header.cmd_id = 1
    msg.header.pdata = b""
    result = decode(msg.SerializeToString())
    assert result == {}


def test_decode_cmd_id_1_dispatches_display_upload() -> None:
    """cmd_func=254, cmd_id=1 → Wave3DisplayPropertyUpload."""
    from ecoflow.private.proto.decoder import decode

    raw = _build_display_payload(
        {"bms_batt_soc": 75.0, "wave_operating_mode": 1},
        enc_type=0, src=1, cmd_id=1,
    )
    result = decode(raw)
    assert result.get("bms_batt_soc") == pytest.approx(75.0)
    assert result.get("wave_operating_mode") == 1


def test_decode_cmd_id_21_also_dispatches_display_upload() -> None:
    """cmd_func=254, cmd_id=21 → also Wave3DisplayPropertyUpload."""
    from ecoflow.private.proto.decoder import decode

    raw = _build_display_payload(
        {"temp_ambient": 24.5},
        enc_type=0, src=1, cmd_id=21,
    )
    result = decode(raw)
    assert result.get("temp_ambient") == pytest.approx(24.5)


# ---------------------------------------------------------------------------
# XOR decryption tests
# ---------------------------------------------------------------------------


def test_decode_enc_type_0_no_decryption_applied() -> None:
    """enc_type=0: pdata is used as-is (no XOR)."""
    from ecoflow.private.proto.decoder import decode

    raw = _build_display_payload(
        {"bms_batt_soc": 42.0},
        enc_type=0, src=1, seq=99,
    )
    result = decode(raw)
    assert result.get("bms_batt_soc") == pytest.approx(42.0)


def test_decode_xor_decryption_applied_when_enc_type_1_src_not_32() -> None:
    """enc_type=1, src!=32: pdata is XOR-decrypted with (seq & 0xFF)."""
    from ecoflow.private.proto.decoder import decode

    # _build_display_payload applies XOR encryption when enc_type=1, src!=32.
    # decode() must reverse it to recover the original field values.
    raw = _build_display_payload(
        {"bms_batt_soc": 80.0, "temp_ambient": 23.0},
        enc_type=1, src=1, seq=42,
    )
    result = decode(raw)
    assert result.get("bms_batt_soc") == pytest.approx(80.0)
    assert result.get("temp_ambient") == pytest.approx(23.0)


def test_decode_src_32_skips_decryption_even_if_enc_type_1() -> None:
    """enc_type=1, src=32: pdata is NOT XOR'd (app-originated messages skip decrypt).

    QUIRK: src=32 means the message came from the app (i.e., our own command).
    The firmware does not encrypt app-originated messages even when enc_type=1.
    decode() must pass pdata through without XOR when src=32.
    """
    from ecoflow.private.proto.decoder import decode

    # src=32, so _build_display_payload does NOT XOR-encrypt the pdata.
    # decode() must also NOT attempt to XOR-decrypt it.
    raw = _build_display_payload(
        {"bms_batt_soc": 55.0},
        enc_type=1, src=32, seq=42,
    )
    result = decode(raw)
    assert result.get("bms_batt_soc") == pytest.approx(55.0)


def test_decode_xor_key_is_seq_low_byte_only() -> None:
    """XOR key is seq & 0xFF (only the low byte of seq is used as the key)."""
    from ecoflow.private.proto.decoder import decode

    # seq=0x1FF (511) — low byte is 0xFF
    raw_high_seq = _build_display_payload(
        {"bms_batt_soc": 60.0},
        enc_type=1, src=1, seq=0x1FF,
    )
    result = decode(raw_high_seq)
    assert result.get("bms_batt_soc") == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Field extraction tests
# ---------------------------------------------------------------------------


def test_decode_extracts_all_battery_fields() -> None:
    """Battery SOC and time fields are extracted from Wave3DisplayPropertyUpload."""
    from ecoflow.private.proto.decoder import decode

    raw = _build_display_payload({
        "bms_batt_soc": 68.0,
        "cms_batt_soc": 70.0,
        "cms_dsg_rem_time": 120,
        "cms_chg_rem_time": 45,
    })
    result = decode(raw)

    assert result.get("bms_batt_soc") == pytest.approx(68.0)
    assert result.get("cms_batt_soc") == pytest.approx(70.0)
    assert result.get("cms_dsg_rem_time") == 120
    assert result.get("cms_chg_rem_time") == 45


def test_decode_extracts_power_fields() -> None:
    """Power input/output and source fields are extracted."""
    from ecoflow.private.proto.decoder import decode

    raw = _build_display_payload({
        "pow_in_sum_w": 500.0,
        "pow_out_sum_w": 480.0,
        "pow_get_ac": 400.0,
        "pow_get_pv": 100.0,
    })
    result = decode(raw)

    assert result.get("pow_in_sum_w") == pytest.approx(500.0)
    assert result.get("pow_out_sum_w") == pytest.approx(480.0)
    assert result.get("pow_get_ac") == pytest.approx(400.0)
    assert result.get("pow_get_pv") == pytest.approx(100.0)


def test_decode_is_on_derivation_fields_present() -> None:
    """dev_sleep_state and wave_operating_mode are extracted for is_on derivation."""
    from ecoflow.private.proto.decoder import decode

    raw = _build_display_payload({
        "dev_sleep_state": 0,
        "wave_operating_mode": 1,
    })
    result = decode(raw)

    assert "dev_sleep_state" in result
    assert "wave_operating_mode" in result
```

**Step 2: Run the tests — expect FAIL**
```bash
uv run pytest tests/test_private_decoder.py -v
```
Expected: `ModuleNotFoundError: No module named 'ecoflow.private.proto.decoder'`

**Step 3: Implement `decoder.py`**

Create `src/ecoflow/private/proto/decoder.py`:

```python
"""Wave 3 Protobuf decoder — decrypts and parses raw MQTT payloads.

Entry point: decode(raw_bytes) -> dict[str, Any]
Returns empty dict on any failure — never raises.
"""

from __future__ import annotations

from typing import Any

from ecoflow.private.proto import wave3_pb2


def decode(raw: bytes) -> dict[str, Any]:
    """Decode a raw Wave 3 MQTT Protobuf payload to a flat dict.

    Pipeline:
      1. Parse outer Wave3SetMessage envelope.
      2. If enc_type==1 and src!=32: XOR-decrypt pdata with (seq & 0xFF).
      3. Dispatch inner message by cmd_func/cmd_id.
      4. Flatten proto fields to a dict.
      5. Extract per-mode setpoints from wave_mode_info.

    Returns {} on any failure — empty bytes, invalid proto, unknown cmd.
    """
    try:
        msg = wave3_pb2.Wave3SetMessage()
        msg.ParseFromString(raw)
        if not msg.HasField("header"):
            return {}

        h = msg.header
        pdata: bytes = h.pdata

        # QUIRK: XOR decryption.
        # enc_type==1 and src!=32 means pdata is XOR'd with (seq & 0xFF).
        # src=32 = message originated from the app (our own commands) — skip decrypt.
        # Source: tolwi/hassio-ecoflow-cloud wave3.py decoder logic.
        if getattr(h, "enc_type", 0) == 1 and getattr(h, "src", 0) != 32:
            seq = getattr(h, "seq", 0)
            pdata = bytes(b ^ (seq & 0xFF) for b in pdata)

        cmd_func = getattr(h, "cmd_func", 0)
        cmd_id = getattr(h, "cmd_id", 0)

        if cmd_func == 254 and cmd_id in (1, 21):
            inner: Any = wave3_pb2.Wave3DisplayPropertyUpload()
        elif cmd_func == 254 and cmd_id == 22:
            inner = wave3_pb2.Wave3RuntimePropertyUpload()
        else:
            return {}  # ACKs and unknown cmd types ignored

        inner.ParseFromString(pdata)
        result: dict[str, Any] = {f.name: v for f, v in inner.ListFields()}
        _extract_mode_params(inner, result)
        return result

    except Exception:  # noqa: BLE001
        return {}


def _extract_mode_params(msg: Any, result: dict[str, Any]) -> None:
    """Pull per-mode temp/fan/humidity setpoints from wave_mode_info.

    The Wave 3 stores setpoints for each operating mode in a list indexed
    by wave_operating_mode. We extract the active mode's settings and
    prefix them with 'current_' to distinguish from raw measurements.
    """
    try:
        if not msg.HasField("wave_mode_info"):
            return
        mode = result.get("wave_operating_mode", 0)
        mode_list = msg.wave_mode_info.list_info
        if mode < 1 or mode >= len(mode_list):
            return
        active = mode_list[mode]
        for attr in (
            "submode",
            "airflow_speed",
            "temp_set",
            "humi_set",
            "temp_thermostatic_upper_limit",
            "temp_thermostatic_lower_limit",
        ):
            if active.HasField(attr):
                result[f"current_{attr}"] = getattr(active, attr)
    except Exception:  # noqa: BLE001
        pass
```

**Step 4: Run the tests — expect PASS**
```bash
uv run pytest tests/test_private_decoder.py -v
```
Expected: all tests PASS.

If any test fails because `Wave3RuntimePropertyUpload` is not defined in the vendored `wave3_pb2.py`, add this guard to `decoder.py`:
```python
elif cmd_func == 254 and cmd_id == 22:
    if hasattr(wave3_pb2, "Wave3RuntimePropertyUpload"):
        inner = wave3_pb2.Wave3RuntimePropertyUpload()
    else:
        return {}
```

**Step 5: Commit**
```bash
git add src/ecoflow/private/proto/decoder.py tests/test_private_decoder.py
git commit -m "feat: Wave 3 Protobuf decoder with XOR decryption and cmd dispatch"
```

---

### Task 4: Implement `private/auth.py` with unit tests

**Files:**
- Create: `src/ecoflow/private/auth.py`
- Create: `tests/test_private_auth.py`

**Step 1: Write the failing tests**

Create `tests/test_private_auth.py`:

```python
"""Unit tests for Wave 3 private API authentication.

Tests login() with mocked httpx — no real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_login_returns_private_credentials() -> None:
    """login() parses certificateAccount, certificatePassword, userId."""
    from ecoflow.private.auth import PrivateCredentials, login

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": "0",
        "message": "Success",
        "data": {
            "certificateAccount": "mqtt_user@123",
            "certificatePassword": "mqtt_pass_abc",
            "userId": 987654,
        },
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ecoflow.private.auth.httpx.AsyncClient", return_value=mock_client):
        creds = await login("user@example.com", "password123")

    assert isinstance(creds, PrivateCredentials)
    assert creds.certificate_account == "mqtt_user@123"
    assert creds.certificate_password == "mqtt_pass_abc"
    assert creds.user_id == "987654"  # string — converted in auth.py


async def test_login_posts_to_correct_url() -> None:
    """login() POSTs to api.ecoflow.com/auth/login."""
    from ecoflow.private.auth import login

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": "0",
        "data": {
            "certificateAccount": "a",
            "certificatePassword": "b",
            "userId": 1,
        },
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ecoflow.private.auth.httpx.AsyncClient", return_value=mock_client):
        await login("user@example.com", "pw")

    call_args = mock_client.post.call_args
    assert "api.ecoflow.com/auth/login" in call_args[0][0]


async def test_login_sends_email_and_password_in_body() -> None:
    """login() sends email and password as plain text JSON.

    QUIRK: Password sent as plain text — confirmed from tolwi/hassio-ecoflow-cloud.
    No MD5/base64 encoding. If E2E returns auth error, check encoding.
    """
    from ecoflow.private.auth import login

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": "0",
        "data": {
            "certificateAccount": "a",
            "certificatePassword": "b",
            "userId": 1,
        },
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ecoflow.private.auth.httpx.AsyncClient", return_value=mock_client):
        await login("test@example.com", "my_secret_pw")

    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["email"] == "test@example.com"
    assert call_kwargs["json"]["password"] == "my_secret_pw"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


async def test_login_wrong_password_raises_auth_error() -> None:
    """login() raises EcoFlowAuthError when API returns non-zero code."""
    from ecoflow.exceptions import EcoFlowAuthError
    from ecoflow.private.auth import login

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": "1001",
        "message": "username or password error",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ecoflow.private.auth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(EcoFlowAuthError, match="username or password error"):
            await login("user@example.com", "wrong_password")


async def test_login_numeric_code_zero_is_success() -> None:
    """login() accepts code=0 (integer) in addition to code='0' (string)."""
    from ecoflow.private.auth import PrivateCredentials, login

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": 0,   # integer, not string
        "data": {
            "certificateAccount": "u",
            "certificatePassword": "p",
            "userId": 42,
        },
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ecoflow.private.auth.httpx.AsyncClient", return_value=mock_client):
        creds = await login("user@example.com", "pw")

    assert isinstance(creds, PrivateCredentials)


async def test_login_missing_data_field_raises_auth_error() -> None:
    """login() raises EcoFlowAuthError when response is missing 'data' key."""
    from ecoflow.exceptions import EcoFlowAuthError
    from ecoflow.private.auth import login

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": "0",
        # 'data' key is missing
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ecoflow.private.auth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises((EcoFlowAuthError, KeyError)):
            await login("user@example.com", "pw")


# ---------------------------------------------------------------------------
# PrivateCredentials dataclass
# ---------------------------------------------------------------------------


def test_private_credentials_is_frozen() -> None:
    """PrivateCredentials is a frozen dataclass — fields cannot be reassigned."""
    from ecoflow.private.auth import PrivateCredentials

    creds = PrivateCredentials(
        certificate_account="acc",
        certificate_password="pw",
        user_id="123",
    )
    with pytest.raises((AttributeError, TypeError)):
        creds.certificate_account = "other"  # type: ignore[misc]
```

**Step 2: Run the tests — expect FAIL**
```bash
uv run pytest tests/test_private_auth.py -v
```
Expected: `ModuleNotFoundError: No module named 'ecoflow.private.auth'`

**Step 3: Implement `auth.py`**

Create `src/ecoflow/private/auth.py`:

```python
"""EcoFlow private API authentication — email/password login.

Authenticates against api.ecoflow.com/auth/login to obtain MQTT credentials.
Used by Wave3Connection; not required for the public Developer API.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ecoflow.exceptions import EcoFlowAuthError


@dataclass(frozen=True)
class PrivateCredentials:
    """MQTT credentials returned by the EcoFlow private login endpoint.

    These are distinct from EcoFlowCredentials (access/secret key pair).
    They are used as MQTT username/password for mqtt.ecoflow.com:8883.
    """

    certificate_account: str   # MQTT username
    certificate_password: str  # MQTT password
    user_id: str               # used in MQTT client_id construction


async def login(email: str, password: str) -> PrivateCredentials:
    """Authenticate with EcoFlow private API using app email/password.

    QUIRK: Password is sent as plain text in the JSON body.
    Confirmed from tolwi/hassio-ecoflow-cloud implementation (MIT).
    If E2E returns auth error, check if MD5/base64 encoding is needed
    and update this comment and the json body accordingly.

    Raises:
        EcoFlowAuthError: if the API returns a non-zero code or wrong credentials.
    """
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            "https://api.ecoflow.com/auth/login",
            json={"email": email, "password": password},
            headers={"lang": "en_US", "country": "US"},
            timeout=30.0,
        )
        body = resp.json()
        if str(body.get("code", "-1")) != "0":
            raise EcoFlowAuthError(body.get("message", "login failed"))
        try:
            data = body["data"]
            return PrivateCredentials(
                certificate_account=data["certificateAccount"],
                certificate_password=data["certificatePassword"],
                user_id=str(data["userId"]),
            )
        except KeyError as exc:
            raise EcoFlowAuthError(
                f"login response missing expected field: {exc}"
            ) from exc
```

**Step 4: Run the tests — expect PASS**
```bash
uv run pytest tests/test_private_auth.py -v
```
Expected: all 7 tests PASS.

**Step 5: Commit**
```bash
git add src/ecoflow/private/auth.py tests/test_private_auth.py
git commit -m "feat: Wave 3 private API auth — login() returns PrivateCredentials"
```

---

### Task 5: Update `Wave3Status` model and fix all cascaded test failures

This task replaces the old Wave3Status (which used JSON `pd/bms` format) with the real
Protobuf field names from `wave3_pb2.pyi`. **Several existing tests will break** — fixing
them is part of this task.

**Files:**
- Modify: `src/ecoflow/models/wave3.py`  (full replacement)
- Create: `tests/test_models_wave3_private.py`  (new tests for new behavior)
- Modify: `tests/test_models_wave3.py`  (update for new enum names/defaults)
- Modify: `tests/test_device_wave3.py`  (update for new enum names/defaults)
- Modify: `tests/test_package_exports.py`  (fix `Wave3Mode.COOL` reference)

**Step 1: Write failing tests for the new behavior**

Create `tests/test_models_wave3_private.py`:

```python
"""Tests for Wave3Status private API model (proto-based field names).

All fields validated against wave3_pb2.pyi from tolwi/hassio-ecoflow-cloud.
Temperatures are native float °C — NOT multiplied by 10.
"""

from __future__ import annotations

import pytest

from ecoflow.models.wave3 import Wave3Mode, Wave3Status

SN = "AC71ZK1APJ410297"


# ---------------------------------------------------------------------------
# Wave3Mode enum
# ---------------------------------------------------------------------------


def test_wave3_mode_none_is_zero() -> None:
    """Wave3Mode.NONE == 0 (off/standby)."""
    assert Wave3Mode.NONE.value == 0


def test_wave3_mode_cooling_is_1() -> None:
    """Wave3Mode.COOLING == 1."""
    assert Wave3Mode.COOLING.value == 1


def test_wave3_mode_heating_is_2() -> None:
    """Wave3Mode.HEATING == 2."""
    assert Wave3Mode.HEATING.value == 2


def test_wave3_mode_venting_is_3() -> None:
    """Wave3Mode.VENTING == 3 (fan-only)."""
    assert Wave3Mode.VENTING.value == 3


def test_wave3_mode_dehumidifying_is_4() -> None:
    """Wave3Mode.DEHUMIDIFYING == 4."""
    assert Wave3Mode.DEHUMIDIFYING.value == 4


def test_wave3_mode_thermostatic_is_5() -> None:
    """Wave3Mode.THERMOSTATIC == 5 (thermostat range mode)."""
    assert Wave3Mode.THERMOSTATIC.value == 5


# ---------------------------------------------------------------------------
# is_on derivation — the tricky two-field logic
# ---------------------------------------------------------------------------


def test_is_on_true_when_both_conditions_met() -> None:
    """is_on=True only when dev_sleep_state != 1 AND wave_operating_mode != 0."""
    status = Wave3Status.from_mqtt_payload(SN, {
        "dev_sleep_state": 0,
        "wave_operating_mode": 1,   # COOLING
    })
    assert status.is_on is True


def test_is_on_false_when_sleep_state_is_1() -> None:
    """dev_sleep_state=1 means OFF regardless of operating mode.

    QUIRK: dev_sleep_state=1 means the device is powered off at hardware level.
    Even if wave_operating_mode is non-zero, the unit is off.
    """
    status = Wave3Status.from_mqtt_payload(SN, {
        "dev_sleep_state": 1,
        "wave_operating_mode": 1,   # COOLING — but unit is off
    })
    assert status.is_on is False


def test_is_on_false_when_operating_mode_is_zero() -> None:
    """wave_operating_mode=0 (NONE) means no active mode — device is off."""
    status = Wave3Status.from_mqtt_payload(SN, {
        "dev_sleep_state": 0,
        "wave_operating_mode": 0,
    })
    assert status.is_on is False


def test_is_on_false_when_both_indicate_off() -> None:
    """Both dev_sleep_state=1 and wave_operating_mode=0 — device is off."""
    status = Wave3Status.from_mqtt_payload(SN, {
        "dev_sleep_state": 1,
        "wave_operating_mode": 0,
    })
    assert status.is_on is False


def test_is_on_false_when_all_defaults() -> None:
    """Empty payload → is_on=False (default for both guard fields is off)."""
    status = Wave3Status.from_mqtt_payload(SN, {})
    assert status.is_on is False


# ---------------------------------------------------------------------------
# fan_level mapping — 20/40/60/80/100 raw → 1/2/3/4/5 level
# ---------------------------------------------------------------------------


def test_fan_level_20_maps_to_1() -> None:
    """airflow_speed raw=20 → fan_level=1."""
    status = Wave3Status.from_mqtt_payload(SN, {"current_airflow_speed": 20})
    assert status.fan_level == 1
    assert status.airflow_speed == 20


def test_fan_level_40_maps_to_2() -> None:
    assert Wave3Status.from_mqtt_payload(SN, {"current_airflow_speed": 40}).fan_level == 2


def test_fan_level_60_maps_to_3() -> None:
    assert Wave3Status.from_mqtt_payload(SN, {"current_airflow_speed": 60}).fan_level == 3


def test_fan_level_80_maps_to_4() -> None:
    assert Wave3Status.from_mqtt_payload(SN, {"current_airflow_speed": 80}).fan_level == 4


def test_fan_level_100_maps_to_5() -> None:
    assert Wave3Status.from_mqtt_payload(SN, {"current_airflow_speed": 100}).fan_level == 5


def test_fan_level_unknown_speed_defaults_to_1() -> None:
    """Unexpected raw speed (e.g., 50) maps to fan_level=1 as safe default."""
    status = Wave3Status.from_mqtt_payload(SN, {"current_airflow_speed": 50})
    assert status.fan_level == 1


# ---------------------------------------------------------------------------
# Temperature — native float °C, NOT multiplied by 10
# ---------------------------------------------------------------------------


def test_temperatures_are_native_celsius_not_x10() -> None:
    """Temperatures are float °C directly — no ×10 scaling.

    QUIRK: Some community sources claimed ×10 encoding. This is WRONG.
    Proto declares temp_set: float. Tolwi applies no division.
    This test is a regression guard — do not divide by 10 anywhere.
    """
    status = Wave3Status.from_mqtt_payload(SN, {
        "temp_ambient": 24.5,
        "temp_indoor_supply_air": 18.0,
        "current_temp_set": 22.0,
    })
    assert status.ambient_temp == pytest.approx(24.5)
    assert status.supply_air_temp == pytest.approx(18.0)
    assert status.target_temp == pytest.approx(22.0)


def test_target_temp_default_is_22() -> None:
    """Default target_temp is 22.0°C (not 26.0 — that was the old JSON model)."""
    status = Wave3Status.from_mqtt_payload(SN, {})
    assert status.target_temp == pytest.approx(22.0)


# ---------------------------------------------------------------------------
# All key fields from a cooling payload
# ---------------------------------------------------------------------------


def test_from_mqtt_payload_full_cooling_payload() -> None:
    """from_mqtt_payload maps all major fields from a realistic Protobuf dict."""
    data = {
        "dev_sleep_state": 0,
        "wave_operating_mode": 1,    # COOLING
        "bms_batt_soc": 75.0,
        "cms_batt_soc": 73.0,
        "temp_ambient": 28.5,
        "temp_indoor_supply_air": 16.0,
        "current_temp_set": 22.0,
        "current_airflow_speed": 60,
        "current_submode": 0,
        "humi_ambient": 55.0,
        "current_humi_set": 50.0,
        "pow_in_sum_w": 900.0,
        "pow_out_sum_w": 850.0,
        "pow_get_ac": 900.0,
        "pow_get_pv": 0.0,
        "cms_dsg_rem_time": 90,
        "cms_chg_rem_time": 0,
        "condensate_water_level": 15,
    }
    status = Wave3Status.from_mqtt_payload(SN, data)

    assert status.sn == SN
    assert status.online is True
    assert status.is_on is True
    assert status.mode == Wave3Mode.COOLING
    assert status.battery_soc == pytest.approx(75.0)
    assert status.system_soc == pytest.approx(73.0)
    assert status.ambient_temp == pytest.approx(28.5)
    assert status.supply_air_temp == pytest.approx(16.0)
    assert status.target_temp == pytest.approx(22.0)
    assert status.fan_level == 3      # 60 → 3
    assert status.airflow_speed == 60
    assert status.ambient_humidity == pytest.approx(55.0)
    assert status.target_humidity == pytest.approx(50.0)
    assert status.input_power_watts == pytest.approx(900.0)
    assert status.output_power_watts == pytest.approx(850.0)
    assert status.discharge_time_min == 90
    assert status.water_level == 15
    assert status.updated_at is not None


def test_from_mqtt_payload_sets_sn() -> None:
    """from_mqtt_payload stores the SN on the returned status."""
    status = Wave3Status.from_mqtt_payload("MY-SN-001", {})
    assert status.sn == "MY-SN-001"


def test_from_mqtt_payload_sets_online_true() -> None:
    """from_mqtt_payload always sets online=True."""
    status = Wave3Status.from_mqtt_payload(SN, {})
    assert status.online is True


def test_from_mqtt_payload_sets_updated_at() -> None:
    """from_mqtt_payload sets updated_at to a non-None datetime."""
    status = Wave3Status.from_mqtt_payload(SN, {})
    assert status.updated_at is not None
```

**Step 2: Run the new tests — expect FAIL**
```bash
uv run pytest tests/test_models_wave3_private.py -v
```
Expected: many failures because `Wave3Mode.NONE`, `Wave3Mode.COOLING`, etc. do not exist yet and `from_mqtt_payload` still uses the old JSON format.

**Step 3: Replace `src/ecoflow/models/wave3.py`**

Replace the entire file with the following content:

```python
"""Wave 3 portable air conditioner models for EcoFlow Wave series."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any


class Wave3Mode(IntEnum):
    """Operating mode of the Wave 3 AC unit.

    Source: foxthefox/ioBroker.ecoflow-mqtt wave3.md waveOperatingMode enum.
    Note: value 1 is COOLING, not VENTING — naming confirmed from ioBroker docs.

    QUIRK: submode value 1 is absent from tolwi's _SUBMODE_TO_PRESET mapping.
    Treat as reserved/unknown — display as NONE.
    """

    NONE = 0           # off / standby
    COOLING = 1
    HEATING = 2
    VENTING = 3        # fan-only
    DEHUMIDIFYING = 4
    THERMOSTATIC = 5   # thermostat range mode


@dataclass
class Wave3Status:
    """Status snapshot for EcoFlow Wave 3 portable AC.

    Fields validated against wave3_pb2.pyi from tolwi/hassio-ecoflow-cloud.
    Data arrives via MQTT /app/device/property/{sn} on the private API
    (email/password). The public Developer API returns error 1006 for Wave 3.
    Use Wave3Connection (from ecoflow.private) to receive this data.
    """

    sn: str = ""
    product_name: str = ""
    online: bool = False

    # Power state
    is_on: bool = False
    """Derived from dev_sleep_state AND wave_operating_mode.
    QUIRK: dev_sleep_state=1 means OFF regardless of operating mode.
    is_on = (dev_sleep_state != 1) AND (wave_operating_mode != 0)"""
    mode: Wave3Mode = Wave3Mode.NONE

    # Temperature (all in native °C — NOT multiplied by 10)
    # QUIRK: earlier community sources claimed ×10 encoding — this is WRONG.
    # Proto declares temp_set: float. Tolwi uses float(degrees) directly.
    ambient_temp: float = 0.0           # temp_ambient (current room temp)
    supply_air_temp: float = 0.0        # temp_indoor_supply_air (outlet air)
    target_temp: float = 22.0           # current_temp_set (from wave_mode_info)
    target_temp_high: float = 24.0      # current_temp_thermostatic_upper_limit
    target_temp_low: float = 20.0       # current_temp_thermostatic_lower_limit
    # RuntimePropertyUpload fields (cmd_id=22):
    condenser_temp: float = 0.0         # temp_condenser
    evaporator_temp: float = 0.0        # temp_evaporator
    outdoor_temp: float = 0.0           # temp_outdoor_ambient
    compressor_discharge_temp: float = 0.0  # temp_compressor_discharge

    # Fan — raw values from device: 20/40/60/80/100
    airflow_speed: int = 20             # current_airflow_speed (raw)
    fan_level: int = 1                  # mapped: {20:1, 40:2, 60:3, 80:4, 100:5}
    submode: int = 0   # current_submode: 0=none, 2=boost, 3=sleep, 4=eco
    # QUIRK: value 1 is absent from tolwi's _SUBMODE_TO_PRESET mapping. Reserved.

    # Humidity
    ambient_humidity: float = 0.0       # humi_ambient
    target_humidity: float = 50.0       # current_humi_set

    # Battery (BMS = main pack, CMS = system aggregation)
    battery_soc: float = 0.0           # bms_batt_soc
    system_soc: float = 0.0            # cms_batt_soc
    bms_discharge_time_min: int = 0    # bms_dsg_rem_time
    bms_charge_time_min: int = 0       # bms_chg_rem_time
    discharge_time_min: int = 0        # cms_dsg_rem_time (system)
    charge_time_min: int = 0           # cms_chg_rem_time (system)

    # Power (Watts)
    input_power_watts: float = 0.0     # pow_in_sum_w
    output_power_watts: float = 0.0    # pow_out_sum_w
    ac_power_watts: float = 0.0        # pow_get_ac
    ac_input_power_watts: float = 0.0  # pow_get_ac_in
    battery_power_watts: float = 0.0   # pow_get_bms
    pv_power_watts: float = 0.0        # pow_get_pv
    self_consume_watts: float = 0.0    # pow_get_self_consume

    # Water
    water_level: int = 0               # condensate_water_level (0–100%)

    updated_at: datetime | None = None

    _FAN_SPEED_MAP: dict[int, int] = field(
        default_factory=lambda: {20: 1, 40: 2, 60: 3, 80: 4, 100: 5},
        repr=False,
        compare=False,
    )

    @classmethod
    def from_mqtt_payload(cls, sn: str, data: dict[str, Any]) -> "Wave3Status":
        """Build Wave3Status from a decoded Protobuf payload dict.

        Called by Wave3Device._on_message() after the Protobuf decoder
        produces a flat dict keyed by snake_case proto field names.

        QUIRK: key names come directly from the Protobuf field definitions
        (e.g., 'bms_batt_soc' not 'bmsBattSoc'). Current setpoints are
        prefixed with 'current_' (e.g., 'current_temp_set').
        """
        sleep = int(data.get("dev_sleep_state", 0))
        mode_val = int(data.get("wave_operating_mode", 0))
        raw_speed = int(data.get("current_airflow_speed", 20))
        fan_level = {20: 1, 40: 2, 60: 3, 80: 4, 100: 5}.get(raw_speed, 1)
        return cls(
            sn=sn,
            online=True,
            is_on=(sleep != 1) and (mode_val != 0),
            mode=Wave3Mode(mode_val) if mode_val in range(6) else Wave3Mode.NONE,
            ambient_temp=float(data.get("temp_ambient", 0)),
            supply_air_temp=float(data.get("temp_indoor_supply_air", 0)),
            target_temp=float(data.get("current_temp_set", 22.0)),
            target_temp_high=float(
                data.get("current_temp_thermostatic_upper_limit", 24.0)
            ),
            target_temp_low=float(
                data.get("current_temp_thermostatic_lower_limit", 20.0)
            ),
            condenser_temp=float(data.get("temp_condenser", 0)),
            evaporator_temp=float(data.get("temp_evaporator", 0)),
            outdoor_temp=float(data.get("temp_outdoor_ambient", 0)),
            compressor_discharge_temp=float(
                data.get("temp_compressor_discharge", 0)
            ),
            airflow_speed=raw_speed,
            fan_level=fan_level,
            submode=int(data.get("current_submode", 0)),
            ambient_humidity=float(data.get("humi_ambient", 0)),
            target_humidity=float(data.get("current_humi_set", 50.0)),
            battery_soc=float(data.get("bms_batt_soc", 0)),
            system_soc=float(data.get("cms_batt_soc", 0)),
            bms_discharge_time_min=int(data.get("bms_dsg_rem_time", 0)),
            bms_charge_time_min=int(data.get("bms_chg_rem_time", 0)),
            discharge_time_min=int(data.get("cms_dsg_rem_time", 0)),
            charge_time_min=int(data.get("cms_chg_rem_time", 0)),
            input_power_watts=float(data.get("pow_in_sum_w", 0)),
            output_power_watts=float(data.get("pow_out_sum_w", 0)),
            ac_power_watts=float(data.get("pow_get_ac", 0)),
            ac_input_power_watts=float(data.get("pow_get_ac_in", 0)),
            battery_power_watts=float(data.get("pow_get_bms", 0)),
            pv_power_watts=float(data.get("pow_get_pv", 0)),
            self_consume_watts=float(data.get("pow_get_self_consume", 0)),
            water_level=int(data.get("condensate_water_level", 0)),
            updated_at=datetime.now(UTC),
        )
```

**Step 4: Update `tests/test_models_wave3.py`** (existing file — fix broken tests)

Replace the entire file content:

```python
"""Tests for Wave 3 model basics (enum values, dataclass construction).

The private proto-based from_mqtt_payload() is tested separately
in tests/test_models_wave3_private.py.
"""

from __future__ import annotations

from ecoflow.models.wave3 import Wave3Mode, Wave3Status


def test_wave3_mode_none_value() -> None:
    """Wave3Mode.NONE == 0 — the off/standby state."""
    assert Wave3Mode.NONE.value == 0


def test_wave3_mode_cooling_value() -> None:
    assert Wave3Mode.COOLING.value == 1


def test_wave3_mode_heating_value() -> None:
    assert Wave3Mode.HEATING.value == 2


def test_wave3_mode_venting_value() -> None:
    assert Wave3Mode.VENTING.value == 3


def test_wave3_mode_dehumidifying_value() -> None:
    assert Wave3Mode.DEHUMIDIFYING.value == 4


def test_wave3_mode_thermostatic_value() -> None:
    assert Wave3Mode.THERMOSTATIC.value == 5


def test_wave3_status_default_construction() -> None:
    """Wave3Status can be constructed with only sn."""
    status = Wave3Status(sn="AC71TEST")
    assert status.sn == "AC71TEST"
    assert status.is_on is False
    assert status.online is False
    assert status.target_temp == 22.0   # new default
    assert status.mode == Wave3Mode.NONE


def test_wave3_status_from_empty_payload_has_safe_defaults() -> None:
    """from_mqtt_payload({}) returns all-default Wave3Status."""
    status = Wave3Status.from_mqtt_payload("SN", {})
    assert status.sn == "SN"
    assert status.is_on is False
    assert status.online is True
    assert status.target_temp == 22.0
    assert status.battery_soc == 0.0
```

**Step 5: Update `tests/test_device_wave3.py`** (fix tests that use old enum names and old defaults)

Find and replace the following sections in `tests/test_device_wave3.py`:

In `make_wave3()`, change the mock return value to use proto-style fields:
```python
# OLD:
rest.get_quota = AsyncMock(
    return_value={
        "pd": {
            "powerMode": 1,
            "waveMode": 0,
            "setTemp": 240,
        }
    }
)

# NEW (proto fields that produce is_on=True, mode=COOLING, target_temp=24.0):
rest.get_quota = AsyncMock(
    return_value={
        "dev_sleep_state": 0,
        "wave_operating_mode": 1,
        "current_temp_set": 24.0,
    }
)
```

In `test_wave3_refresh_returns_status`, update the assertion:
```python
# OLD: assert status.target_temp == 24.0
# NEW: assert status.target_temp == pytest.approx(24.0)
```
(Add `import pytest` at top of file if not already there.)

In `test_wave3_refresh_returns_minimal_status_on_api_error`, update:
```python
# OLD: assert status.target_temp == 26.0  # default
# NEW: assert status.target_temp == 22.0  # default in new model
```

In `test_wave3_set_mode_publishes_int_value`, update:
```python
# OLD: await device.set_mode(Wave3Mode.HEAT)
# OLD: mock_publish.assert_called_once_with({"waveMode": 1})
# NEW: await device.set_mode(Wave3Mode.HEATING)
# NEW: mock_publish.assert_called_once_with({"waveMode": 2})
```

**Step 6: Update `tests/test_package_exports.py`**

Find line `assert Wave3Mode.COOL.value == 0` and replace it:
```python
# OLD:
assert Wave3Mode.COOL.value == 0

# NEW:
assert Wave3Mode.NONE.value == 0
```

**Step 7: Run the new tests — expect PASS**
```bash
uv run pytest tests/test_models_wave3_private.py -v
```
Expected: all tests PASS.

**Step 8: Run the full suite to confirm nothing else broke**
```bash
uv run pytest -m "not integration and not write_integration" -q
```
Expected: all tests pass. If any test fails with a `Wave3Mode` attribute error, search for old attribute names:
```bash
grep -r "Wave3Mode\." tests/ --include="*.py"
```
Fix any remaining references to `COOL`, `HEAT`, `FAN`, `DRY`, `AUTO`.

**Step 9: Commit**
```bash
git add src/ecoflow/models/wave3.py \
        tests/test_models_wave3_private.py \
        tests/test_models_wave3.py \
        tests/test_device_wave3.py \
        tests/test_package_exports.py
git commit -m "feat: update Wave3Status and Wave3Mode for private Protobuf API"
```

---

### Task 6: Fix `Wave3Device.refresh()` for `rest=None`

**Files:**
- Modify: `src/ecoflow/devices/wave3.py`
- Modify: `tests/test_device_wave3.py`  (add one new test)

**Step 1: Write the failing test**

Add this test to the end of `tests/test_device_wave3.py`:

```python
@pytest.mark.asyncio
async def test_wave3_refresh_with_rest_none_returns_status_without_api_call() -> None:
    """refresh() with rest=None returns current status — no REST call attempted.

    This is the private API path: Wave3Connection creates Wave3Device with
    rest=None because the private API has no REST quota endpoint.
    """
    device = Wave3Device(sn="AC71TEST", product_name="Wave 3", rest=None)

    # First call — no status yet — returns a minimal Wave3Status
    status = await device.refresh()
    assert status is not None
    assert status.sn == "AC71TEST"
    assert status.online is True
    assert status.product_name == "Wave 3"

    # Simulate MQTT update — set a status on the device
    device.status = Wave3Status(sn="AC71TEST", product_name="Wave 3", online=True, is_on=True)

    # Second call — returns the existing status
    status2 = await device.refresh()
    assert status2.is_on is True


@pytest.mark.asyncio
async def test_wave3_refresh_with_rest_none_does_not_call_rest() -> None:
    """refresh() with rest=None never touches the REST client."""
    device = Wave3Device(sn="AC71TEST", product_name="Wave 3", rest=None)
    # If this tries to call self._rest.get_quota(), it will raise AttributeError
    # because None has no get_quota attribute.
    # The test passes if refresh() completes without raising.
    status = await device.refresh()
    assert status is not None
```

**Step 2: Run the tests — expect FAIL**
```bash
uv run pytest tests/test_device_wave3.py::test_wave3_refresh_with_rest_none_returns_status_without_api_call tests/test_device_wave3.py::test_wave3_refresh_with_rest_none_does_not_call_rest -v
```
Expected: `AttributeError: 'NoneType' object has no attribute 'get_quota'`

**Step 3: Fix `refresh()` in `src/ecoflow/devices/wave3.py`**

Find the `refresh()` method and add a guard at the top:

```python
async def refresh(self) -> Wave3Status:
    """Fetch current Wave 3 status via REST.

    NOTE: Wave 3 returns error 1006 from the public REST API
    (device is not allowed to get device info). When this happens,
    a minimal status with online=True is returned with all reading
    fields at defaults. Data arrives via MQTT on the private API only.

    NOTE: rest=None is valid for the private API path — Wave3Connection
    passes rest=None and data arrives via MQTT only.
    """
    if self._rest is None:
        # Private API path — no REST quota available for Wave 3.
        # Return current status if available, otherwise return minimal status.
        if self.status is None:
            self.status = Wave3Status(
                sn=self.sn,
                product_name=self.product_name,
                online=True,
            )
        return self.status
    try:
        raw = await self._rest.get_quota(self.sn)
        ...
```

Leave the rest of `refresh()` unchanged.

**Step 4: Run the tests — expect PASS**
```bash
uv run pytest tests/test_device_wave3.py -v
```
Expected: all tests PASS, including the two new ones.

**Step 5: Commit**
```bash
git add src/ecoflow/devices/wave3.py tests/test_device_wave3.py
git commit -m "feat: Wave3Device.refresh() handles rest=None for private API path"
```

---

### Task 7: Full test suite validation

**Step 1: Run the complete non-integration test suite**
```bash
uv run pytest -m "not integration and not write_integration" -q
```
Expected: **all tests pass**. Zero failures, zero errors.

If there are failures:
- `AttributeError: type object 'Wave3Mode' has no attribute 'COOL'` → search `grep -r "Wave3Mode\.COOL\|Wave3Mode\.HEAT\|Wave3Mode\.FAN" tests/ src/` and fix remaining old references
- `ModuleNotFoundError: No module named 'ecoflow.private'` → verify all `__init__.py` files were created in Task 2
- `google.protobuf` import error → run `uv sync` again

**Step 2: Run a quick lint check**
```bash
uv run ruff check src/ecoflow/private/ tests/test_private_*.py tests/test_models_wave3_private.py --fix
```
Expected: no issues (or auto-fixed).

**Step 3: Final Phase 1 commit**
```bash
git add -A
git commit -m "feat: Wave 3 Phase 1 complete — proto schema, decoder, auth, updated model"
```

---

## Phase 1 completion checklist

Before handing off to Phase 2, verify all of these are true:

- [ ] `uv run python -c "import ecoflow.private.proto.wave3_pb2"` — no error
- [ ] `uv run python -c "from ecoflow.private.auth import login"` — no error
- [ ] `uv run python -c "from ecoflow.private.proto.decoder import decode"` — no error
- [ ] `uv run python -c "from ecoflow.models.wave3 import Wave3Mode; print(Wave3Mode.COOLING)"` — prints `Wave3Mode.COOLING`
- [ ] `uv run pytest -m "not integration and not write_integration" -q` — all PASS
- [ ] `src/ecoflow/private/proto/wave3_pb2.py` has the attribution comment at the top
