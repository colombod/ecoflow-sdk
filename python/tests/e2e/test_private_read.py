"""Read-only E2E integration tests for Wave 3 private API.

Run with: uv run pytest tests/e2e/test_private_read.py -m integration -v --timeout=60

Credentials loaded from tests/.env:
  ECOFLOW_EMAIL
  ECOFLOW_PASSWORD
  ECOFLOW_WAVE3_SN
"""

from __future__ import annotations

import asyncio

import pytest

from ecoflow.private.auth import PrivateCredentials, login
from ecoflow.private.connection import Wave3Connection
from tests.conftest import get_private_email, get_private_password, get_wave3_sn

# ---------------------------------------------------------------------------
# Test 1 — login() returns PrivateCredentials with real credentials
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_private_login_succeeds() -> None:
    """Login returns PrivateCredentials with non-empty MQTT credentials.

    Failure hint: if EcoFlowAuthError, check password encoding —
    may need hashlib.md5(password.encode()).hexdigest().
    """
    email = get_private_email()
    password = get_private_password()

    creds = await login(email, password)

    assert isinstance(creds, PrivateCredentials)
    assert creds.certificate_account, "certificate_account must not be empty"
    assert creds.certificate_password, "certificate_password must not be empty"
    assert creds.user_id, "user_id must not be empty"


# ---------------------------------------------------------------------------
# Test 2 — Wave3Connection.connect() establishes MQTT connection
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_private_connects() -> None:
    """Wave3Connection.connect() establishes MQTT and populates devices dict.

    Failure hint: if times out, check mqtt.ecoflow.com:8883 reachability
    and that PrivateCredentials are valid.
    """
    email = get_private_email()
    password = get_private_password()
    sn = get_wave3_sn()

    conn = Wave3Connection(email=email, password=password, device_sns=[sn])
    await conn.connect()

    assert sn in conn.devices
    assert conn._task is not None
    assert not conn._task.done()

    await conn.close()


# ---------------------------------------------------------------------------
# Test 3 — Wave3Connection pushes device status within 30s
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_private_receives_status() -> None:
    """Wave3Connection pushes Wave3Status via MQTT within 30s.

    Polls device.status every 0.5s for up to 30s until updated_at is set.
    Failure hint: if all default values, check cmd_func/cmd_id dispatch in decoder.py.
    """
    email = get_private_email()
    password = get_private_password()
    sn = get_wave3_sn()

    async with Wave3Connection(email=email, password=password, device_sns=[sn]) as conn:
        device = conn.devices[sn]

        # Poll for up to 30s (0.5s intervals = 60 iterations)
        status = None
        for _ in range(60):
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.updated_at is not None:
                status = device.status
                break

        assert status is not None, (
            f"No status received for Wave 3 device {sn} within 30s. "
            "Check mqtt.ecoflow.com:8883 reachability "
            "and that PrivateCredentials are valid."
        )

        # Core assertions
        assert status.sn == sn, f"Expected sn={sn!r}, got {status.sn!r}"
        assert status.online is True, f"{sn}: device must be online"
        assert status.updated_at is not None, f"{sn}: updated_at must be set"

        # Diagnostic output (visible with pytest -s)
        print(
            f"\n[Wave 3 Status] sn={status.sn} online={status.online} "
            f"battery_soc={status.battery_soc} ambient_temp={status.ambient_temp} "
            f"mode={status.mode} updated_at={status.updated_at}"
        )

        # At least one sensor reading must be non-default (non-zero)
        has_non_default = (
            status.battery_soc != 0.0
            or status.ambient_temp != 0.0
            or status.mode.value != 0
        )
        assert has_non_default, (
            f"{sn}: all sensor fields are at default values "
            f"(battery_soc={status.battery_soc}, "
            f"ambient_temp={status.ambient_temp}, "
            f"mode={status.mode.value}). "
            "Check cmd_func/cmd_id dispatch in decoder.py."
        )
