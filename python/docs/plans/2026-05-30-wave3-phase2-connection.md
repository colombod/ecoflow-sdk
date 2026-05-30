# Wave 3 Private API — Phase 2: Connection + Integration

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Prerequisite:** Phase 1 must be complete. Verify: `uv run pytest -m "not integration and not write_integration" -q` — all tests pass.

**Goal:** Wire up `Wave3Connection` — the MQTT connection class that ties together auth, decoding, and Wave3Device state management. Add top-level exports, E2E integration tests, credential helpers, and user-facing documentation.
**Architecture:** `Wave3Connection` is an async context manager that calls `login()`, creates `Wave3Device` instances, starts a background MQTT loop using `aiomqtt` directly (not the existing `MqttTransport`), and routes decoded Protobuf payloads to device state. Users import it from `ecoflow.private` or from the top-level `ecoflow` package.
**Tech Stack:** Python 3.11, aiomqtt (already installed), asyncio, ssl, unittest.mock (for unit tests), pytest-asyncio.

---

## Before you start

All commands run from `ecoflow-python/python/` (the directory containing `pyproject.toml`).
Phase 1 must be complete — all of the following files must exist:
```
src/ecoflow/private/__init__.py
src/ecoflow/private/auth.py
src/ecoflow/private/proto/__init__.py
src/ecoflow/private/proto/wave3_pb2.py
src/ecoflow/private/proto/decoder.py
```

Verify:
```bash
uv run python -c "from ecoflow.private.auth import login; print('Phase 1 OK')"
```

---

### Task 1: Implement `Wave3Connection` with lifecycle unit tests

**Files:**
- Create: `src/ecoflow/private/connection.py`
- Create: `tests/test_private_connection.py`

**Step 1: Write the failing tests**

Create `tests/test_private_connection.py`:

```python
"""Unit tests for Wave3Connection lifecycle.

Tests connect/close/context-manager using mocked login() and mocked _run().
No real network calls — no credentials required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ecoflow.devices.wave3 import Wave3Device
from ecoflow.private.auth import PrivateCredentials
from ecoflow.private.connection import Wave3Connection

FAKE_CREDS = PrivateCredentials(
    certificate_account="mqtt_account@123",
    certificate_password="mqtt_password_abc",
    user_id="987654",
)


def _make_conn(*sns: str) -> Wave3Connection:
    """Build a Wave3Connection with test credentials and given device SNs."""
    return Wave3Connection(
        email="test@example.com",
        password="test_pass",
        device_sns=list(sns),
    )


async def _fake_run(conn: Wave3Connection, creds: PrivateCredentials) -> None:
    """Simulate a _run() that immediately signals ready and then waits."""
    conn._ready.set()
    await asyncio.sleep(100)  # block until cancelled


# ---------------------------------------------------------------------------
# Construction — devices dict is empty before connect()
# ---------------------------------------------------------------------------


def test_devices_empty_before_connect() -> None:
    """Wave3Connection.devices is empty dict before connect() is called."""
    conn = _make_conn("AC71TEST001")
    assert conn.devices == {}


def test_construction_does_not_call_login() -> None:
    """Creating Wave3Connection does not trigger any network calls."""
    with patch("ecoflow.private.connection.login") as mock_login:
        _make_conn("AC71TEST001")
    mock_login.assert_not_called()


# ---------------------------------------------------------------------------
# connect() — devices populated, task started
# ---------------------------------------------------------------------------


async def test_connect_populates_devices_dict() -> None:
    """connect() populates devices dict with one Wave3Device per SN."""
    conn = _make_conn("AC71TEST001", "AC71TEST002")

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        await conn.connect()

    assert "AC71TEST001" in conn.devices
    assert "AC71TEST002" in conn.devices

    await conn.close()


async def test_connect_creates_wave3_device_instances() -> None:
    """Each device in conn.devices is a Wave3Device with rest=None."""
    conn = _make_conn("AC71TEST001")

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        await conn.connect()

    device = conn.devices["AC71TEST001"]
    assert isinstance(device, Wave3Device)
    assert device.sn == "AC71TEST001"
    assert device.product_name == "Wave 3"
    assert device._rest is None  # private API — no REST transport

    await conn.close()


async def test_connect_calls_login_once() -> None:
    """connect() calls login() exactly once with the provided credentials."""
    conn = _make_conn("AC71TEST001")
    mock_login = AsyncMock(return_value=FAKE_CREDS)

    with patch("ecoflow.private.connection.login", new=mock_login), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        await conn.connect()

    mock_login.assert_called_once_with("test@example.com", "test_pass")

    await conn.close()


# ---------------------------------------------------------------------------
# close() — background task cancelled
# ---------------------------------------------------------------------------


async def test_close_cancels_background_task() -> None:
    """close() cancels the background MQTT task."""
    conn = _make_conn("AC71TEST001")

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        await conn.connect()

    task = conn._task
    assert task is not None
    assert not task.done()

    await conn.close()

    assert task.done()


async def test_close_is_idempotent() -> None:
    """Calling close() twice does not raise."""
    conn = _make_conn("AC71TEST001")

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        await conn.connect()

    await conn.close()
    await conn.close()  # second call — must not raise


# ---------------------------------------------------------------------------
# Context manager — __aenter__ / __aexit__
# ---------------------------------------------------------------------------


async def test_context_manager_calls_connect_and_close() -> None:
    """async with Wave3Connection(...) calls connect() then close()."""
    conn = _make_conn("AC71TEST001")

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        async with conn:
            assert "AC71TEST001" in conn.devices

    # After exiting the context, task should be done
    assert conn._task is None or conn._task.done()


async def test_context_manager_returns_self() -> None:
    """'as' clause in async with receives the Wave3Connection instance."""
    conn = _make_conn("AC71TEST001")

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=lambda c: _fake_run(conn, c)):
        async with conn as wave3:
            assert wave3 is conn


# ---------------------------------------------------------------------------
# connect() timeout — _ready never set
# ---------------------------------------------------------------------------


async def test_connect_raises_timeout_if_ready_never_set() -> None:
    """connect() raises TimeoutError if MQTT doesn't connect within 15s.

    We simulate this by making _run() never set conn._ready.
    The timeout is patched to 0.05s so the test runs fast.
    """
    conn = _make_conn("AC71TEST001")

    async def _run_that_never_signals(creds: PrivateCredentials) -> None:
        await asyncio.sleep(100)  # ready is never set

    with patch("ecoflow.private.connection.login", new=AsyncMock(return_value=FAKE_CREDS)), \
         patch.object(conn, "_run", side_effect=_run_that_never_signals), \
         patch("ecoflow.private.connection._CONNECT_TIMEOUT_S", 0.05):
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await conn.connect()
```

**Step 2: Run the tests — expect FAIL**
```bash
uv run pytest tests/test_private_connection.py -v
```
Expected: `ModuleNotFoundError: No module named 'ecoflow.private.connection'`

**Step 3: Implement `connection.py`**

Create `src/ecoflow/private/connection.py`:

```python
"""Wave3Connection — MQTT connection for EcoFlow Wave 3 private API.

Uses email/password authentication (PrivateCredentials) and Protobuf decoding.
The public Developer API (accessKey/secretKey) does not support Wave 3 devices —
they return error 1006. Use this class instead.

Usage:
    from ecoflow.private import Wave3Connection

    async with Wave3Connection(
        email="me@example.com",
        password="my_password",
        device_sns=["AC71ZK1APJ410297"],
    ) as wave3:
        device = wave3.devices["AC71ZK1APJ410297"]
        await asyncio.sleep(5)   # wait for first MQTT push
        print(device.status.battery_soc)
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from typing import TYPE_CHECKING

import aiomqtt

from ecoflow.devices.wave3 import Wave3Device
from ecoflow.private.auth import PrivateCredentials, login
from ecoflow.private.proto.decoder import decode

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

# Timeout for MQTT to connect and signal ready. Patched in tests.
_CONNECT_TIMEOUT_S: float = 15.0


class Wave3Connection:
    """Manages Wave 3 device connections via EcoFlow's private MQTT API.

    Authentication: email + password → PrivateCredentials (one-time login).
    Wire format: Protobuf (decoded via ecoflow.private.proto.decoder).
    MQTT broker: mqtt.ecoflow.com:8883 (TLS, NOT the public mqtt-e.ecoflow.com).
    Topic: /app/device/property/{sn} at QoS 1.

    QUIRK: The private broker is the same for EU and US accounts.
    The public API uses mqtt-e.ecoflow.com for EU — do not use that here.
    """

    def __init__(
        self,
        email: str,
        password: str,
        device_sns: list[str],
    ) -> None:
        self._email = email
        self._password = password
        self._sns = device_sns
        self.devices: dict[str, Wave3Device] = {}
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event = asyncio.Event()

    async def connect(self) -> None:
        """Authenticate, create Wave3Device instances, start the MQTT loop.

        Blocks until MQTT is connected and subscribed (up to _CONNECT_TIMEOUT_S).

        Raises:
            EcoFlowAuthError: if email/password are invalid.
            TimeoutError: if MQTT does not connect within _CONNECT_TIMEOUT_S.
        """
        creds = await login(self._email, self._password)
        self.devices = {
            sn: Wave3Device(sn=sn, product_name="Wave 3", rest=None)
            for sn in self._sns
        }
        self._task = asyncio.create_task(self._run(creds))
        try:
            await asyncio.wait_for(
                self._ready.wait(),
                timeout=_CONNECT_TIMEOUT_S,
            )
        except (TimeoutError, asyncio.TimeoutError):
            if self._task and not self._task.done():
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            raise TimeoutError(
                f"Wave3 MQTT connection timed out after {_CONNECT_TIMEOUT_S:.0f}s"
            ) from None

    async def close(self) -> None:
        """Cancel the background MQTT task and wait for it to finish."""
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def __aenter__(self) -> "Wave3Connection":
        """Call connect() and return self."""
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Call close() on context exit."""
        await self.close()

    async def _run(self, creds: PrivateCredentials) -> None:
        """Background MQTT loop — decodes Protobuf, dispatches to Wave3Device.

        Reconnects automatically with exponential backoff on any MQTT exception.
        Backoff: 1s → 2s → 4s → … → 300s cap.

        QUIRK: Uses aiomqtt directly, NOT the existing MqttTransport.
        MqttTransport calls json.loads() on every message and silently discards
        non-JSON content — which is every Wave 3 Protobuf message.
        """
        tls_ctx = ssl.create_default_context()
        backoff = 1.0

        while True:
            try:
                async with aiomqtt.Client(
                    hostname="mqtt.ecoflow.com",  # private broker — NOT mqtt-e
                    port=8883,
                    username=creds.certificate_account,
                    password=creds.certificate_password,
                    identifier=f"{creds.certificate_account}_{int(time.time())}",
                    keepalive=60,
                    tls_context=tls_ctx,
                ) as client:
                    for sn in self.devices:
                        await client.subscribe(f"/app/device/property/{sn}", qos=1)
                    self._ready.set()
                    backoff = 1.0  # reset on successful connect

                    async for message in client.messages:
                        sn = str(message.topic).rsplit("/", 1)[-1]
                        if sn in self.devices:
                            data = decode(bytes(message.payload))
                            if data:
                                self.devices[sn]._handle_message(sn, data)

            except asyncio.CancelledError:
                return  # clean shutdown — do not reconnect

            except Exception as exc:
                self._ready.clear()
                _log.warning(
                    "Wave3 MQTT connection lost (%s), retrying in %.0fs",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)
```

**Step 4: Run the tests — expect PASS**

> **NOTE on `patch.object(conn, "_run", side_effect=...)`:** In the tests, `_run` is patched
> on the *instance* using `side_effect`. When Python calls `self._run(creds)`, the mock's
> `side_effect` is invoked with `creds`. Because `_run` is an `async def`, the `side_effect`
> must be a callable that returns a coroutine. The `_fake_run(conn, creds)` helper is called
> via a lambda: `side_effect=lambda c: _fake_run(conn, c)`.

```bash
uv run pytest tests/test_private_connection.py -v
```
Expected: all tests PASS.

If `test_connect_raises_timeout_if_ready_never_set` fails because `_CONNECT_TIMEOUT_S` is not patchable (it was imported by value), change the `with patch(...)` line to:
```python
with patch("ecoflow.private.connection._CONNECT_TIMEOUT_S", 0.05):
```
If `asyncio.wait_for` already read the constant by the time the patch is active, change `connection.py` to use the module-level variable at call time: `timeout=_CONNECT_TIMEOUT_S` (which it already does, so this should work).

**Step 5: Commit**
```bash
git add src/ecoflow/private/connection.py tests/test_private_connection.py
git commit -m "feat: Wave3Connection — private MQTT with auth, reconnect, Protobuf dispatch"
```

---

### Task 2: Wire `private/__init__.py` to export `Wave3Connection`

**Files:**
- Modify: `src/ecoflow/private/__init__.py`
- Create: `tests/test_private_init.py`

**Step 1: Write the failing test**

Create `tests/test_private_init.py`:

```python
"""Tests for ecoflow.private package public surface."""

from __future__ import annotations


def test_wave3_connection_importable_from_private() -> None:
    """Wave3Connection is importable from ecoflow.private."""
    from ecoflow.private import Wave3Connection

    assert Wave3Connection.__name__ == "Wave3Connection"


def test_wave3_connection_is_correct_class() -> None:
    """ecoflow.private.Wave3Connection is the same as the connection module class."""
    from ecoflow.private import Wave3Connection
    from ecoflow.private.connection import Wave3Connection as ConcreteClass

    assert Wave3Connection is ConcreteClass


def test_private_all_contains_wave3_connection() -> None:
    """ecoflow.private.__all__ includes Wave3Connection."""
    import ecoflow.private as private

    assert hasattr(private, "__all__")
    assert "Wave3Connection" in private.__all__
```

**Step 2: Run the tests — expect FAIL**
```bash
uv run pytest tests/test_private_init.py -v
```
Expected: `ImportError: cannot import name 'Wave3Connection' from 'ecoflow.private'`

**Step 3: Update `src/ecoflow/private/__init__.py`**

Replace the current content with:

```python
"""EcoFlow private API support (Wave 3, email/password authentication).

Provides Wave3Connection for devices not supported by the public Developer API.
Wave 3 portable ACs (SN prefix AC71) return error 1006 from the public REST API —
use this module instead.

Install: pip install ecoflow-python[wave3]

If protobuf is not installed, importing this module raises ImportError with
a clear install instruction — the error appears at import time, not at first use.
"""

try:
    from ecoflow.private.connection import Wave3Connection
except ImportError as exc:
    if "google.protobuf" in str(exc) or "protobuf" in str(exc).lower():
        raise ImportError(
            "ecoflow.private requires the 'protobuf' package.\n"
            "Install it with: pip install ecoflow-python[wave3]\n"
            f"Original error: {exc}"
        ) from exc
    raise

__all__ = ["Wave3Connection"]
```

**Step 4: Run the tests — expect PASS**
```bash
uv run pytest tests/test_private_init.py -v
```
Expected: all 3 tests PASS.

**Step 5: Verify the ImportError message works**

Temporarily verify the ImportError path by running in a fresh Python session without protobuf
(optional — skip if slow to set up). Otherwise trust that the `try/except` path is correct
by code review.

**Step 6: Commit**
```bash
git add src/ecoflow/private/__init__.py tests/test_private_init.py
git commit -m "feat: ecoflow.private exports Wave3Connection with clear protobuf ImportError"
```

---

### Task 3: Add `Wave3Connection` to the top-level `ecoflow` package

**Files:**
- Modify: `src/ecoflow/__init__.py`
- Modify: `tests/test_toplevel_exports.py`

**Step 1: Write the failing test**

In `tests/test_toplevel_exports.py`, add this new test method to the `TestTopLevelExports` class:

```python
def test_wave3_connection_importable(self) -> None:
    from ecoflow import Wave3Connection

    assert Wave3Connection.__name__ == "Wave3Connection"
```

Also update `test_all_list_contains_expected_symbols` — add `"Wave3Connection"` to the `expected` set. Find the `expected = {...}` block and add the new entry:

```python
# In test_all_list_contains_expected_symbols, add to expected set:
"Wave3Connection",
```

The full updated `expected` set should look like:
```python
expected = {
    "EcoFlowClient",
    "EcoFlowCredentials",
    "EcoFlowError",
    "EcoFlowAuthError",
    "EcoFlowConnectionError",
    "EcoFlowDeviceNotFoundError",
    "EcoFlowTimeoutError",
    "EcoFlowDeviceOfflineError",
    "BatteryStatus",
    "SmartPlugData",
    "SmartMeterData",
    "StreamUltraStatus",
    "Wave3Status",
    "Wave3Mode",
    "BatteryDevice",
    "SmartPlugDevice",
    "SmartMeterDevice",
    "MicroInverterDevice",
    "StreamUltraDevice",
    "StreamAcProDevice",
    "Wave3Device",
    "SmartHomePanelDevice",
    "DiscoveredDevice",
    "Wave3Connection",   # NEW
}
```

**Step 2: Run the new test — expect FAIL**
```bash
uv run pytest tests/test_toplevel_exports.py::TestTopLevelExports::test_wave3_connection_importable -v
uv run pytest tests/test_toplevel_exports.py::TestTopLevelExports::test_all_list_contains_expected_symbols -v
```
Expected: both FAIL — `Wave3Connection` not yet in `ecoflow.__init__`.

**Step 3: Update `src/ecoflow/__init__.py`**

Add the following block near the top, after the existing imports:

```python
# Wave3Connection is an optional import — requires pip install ecoflow-python[wave3]
try:
    from ecoflow.private import Wave3Connection
except ImportError:
    pass  # protobuf not installed — Wave3Connection silently unavailable
```

Then add `"Wave3Connection"` to `__all__`:

```python
__all__ = [
    "EcoFlowClient",
    "EcoFlowCredentials",
    "EcoFlowError",
    "EcoFlowAuthError",
    "EcoFlowConnectionError",
    "EcoFlowDeviceNotFoundError",
    "EcoFlowTimeoutError",
    "EcoFlowDeviceOfflineError",
    "BatteryStatus",
    "SmartPlugData",
    "SmartMeterData",
    "StreamUltraStatus",
    "Wave3Status",
    "Wave3Mode",
    "BatteryDevice",
    "SmartPlugDevice",
    "SmartMeterDevice",
    "MicroInverterDevice",
    "StreamUltraDevice",
    "StreamAcProDevice",
    "Wave3Device",
    "SmartHomePanelDevice",
    "DiscoveredDevice",
    "Wave3Connection",  # requires pip install ecoflow-python[wave3]
]
```

**Important:** The `try/except ImportError: pass` pattern means `Wave3Connection` will
be in `__all__` even if protobuf is not installed — but the name won't exist in the module.
That's acceptable (it follows Python stdlib patterns like `readline`). The important thing
is that `from ecoflow import Wave3Connection` raises a clear `ImportError` pointing to
`pip install ecoflow-python[wave3]` if protobuf is missing.

**Step 4: Run the tests — expect PASS**
```bash
uv run pytest tests/test_toplevel_exports.py -v
```
Expected: all tests PASS, including the new `test_wave3_connection_importable`.

**Step 5: Run the full suite to confirm nothing broke**
```bash
uv run pytest -m "not integration and not write_integration" -q
```
Expected: all pass.

**Step 6: Commit**
```bash
git add src/ecoflow/__init__.py tests/test_toplevel_exports.py
git commit -m "feat: export Wave3Connection from top-level ecoflow package"
```

---

### Task 4: Update `conftest.py` and `.env.example` with private credentials

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/.env.example`

No TDD here — these are configuration helpers and documentation.

**Step 1: Update `tests/conftest.py`**

Append these two helper functions after the existing `pytest_collection_modifyitems` function:

```python
# ---------------------------------------------------------------------------
# Private API credential helpers (Wave 3)
# ---------------------------------------------------------------------------


def get_private_email() -> str:
    """Return ECOFLOW_EMAIL from tests/.env, or skip the test.

    Usage in tests:
        email = get_private_email()  # skips the test if not set
    """
    import os

    email = os.getenv("ECOFLOW_EMAIL", "")
    if not email:
        pytest.skip(
            "ECOFLOW_EMAIL not set in tests/.env — skipping private API test"
        )
    return email


def get_private_password() -> str:
    """Return ECOFLOW_PASSWORD from tests/.env, or skip the test."""
    import os

    password = os.getenv("ECOFLOW_PASSWORD", "")
    if not password:
        pytest.skip(
            "ECOFLOW_PASSWORD not set in tests/.env — skipping private API test"
        )
    return password


def get_wave3_sn() -> str:
    """Return ECOFLOW_WAVE3_SN from tests/.env, or skip the test."""
    import os

    sn = os.getenv("ECOFLOW_WAVE3_SN", "")
    if not sn:
        pytest.skip(
            "ECOFLOW_WAVE3_SN not set in tests/.env — skipping private API test"
        )
    return sn
```

**Step 2: Update `tests/.env.example`**

Append the Wave 3 private API section. The file should contain:

```
# Copy this file to tests/.env and fill in your credentials.
# tests/.env is gitignored.
ECOFLOW_ACCESS_KEY=
ECOFLOW_SECRET_KEY=
ECOFLOW_REGION=EU
ECOFLOW_TEST_DEVICE_SN=

# To allow write E2E tests (alters real device state), set BOTH:
#   1. ECOFLOW_ENABLE_WRITE_TESTS=true  (here)
#   2. --enable-write-tests             (pytest CLI flag)
ECOFLOW_ENABLE_WRITE_TESTS=false

# Wave 3 private API credentials (required for @pytest.mark.integration Wave 3 tests)
# These are your EcoFlow app login credentials — NOT the Developer API keys.
# The Wave 3 portable AC uses email/password auth. Error 1006 from public API is expected.
ECOFLOW_EMAIL=
ECOFLOW_PASSWORD=
ECOFLOW_WAVE3_SN=
```

**Step 3: Add the real credentials to `tests/.env` (gitignored)**

Add to `tests/.env` (not `.env.example` — never commit real credentials):
```
ECOFLOW_EMAIL=your_actual_ecoflow_app_email@example.com
ECOFLOW_PASSWORD=your_actual_ecoflow_app_password
ECOFLOW_WAVE3_SN=AC71ZK1APJ410297
```

> Replace the placeholders with the actual Wave 3 device credentials from your EcoFlow account.

**Step 4: Verify conftest helpers parse the env correctly**
```bash
uv run python -c "
import os; os.environ['ECOFLOW_EMAIL'] = 'test@test.com'
from tests.conftest import get_private_email
# Note: this would normally call pytest.skip if missing — set the var first
print('conftest helpers available')
"
```
This is just a sanity check — `pytest.skip` only works inside a test, not bare Python.

**Step 5: Commit**
```bash
git add tests/conftest.py tests/.env.example
git commit -m "chore: add private API credential helpers to conftest and .env.example"
```

---

### Task 5: Write E2E integration tests

**Files:**
- Create: `tests/e2e/test_private_read.py`

**Step 1: Write the E2E tests**

> These tests require real credentials. They are auto-skipped when `tests/.env` is absent
> or credentials are missing. Mark `@pytest.mark.integration`. No write operations.

Create `tests/e2e/test_private_read.py`:

```python
"""Read-only E2E integration tests for Wave 3 private API.

Run with: uv run pytest tests/e2e/test_private_read.py -m integration -v -s --timeout=60

Credentials loaded from tests/.env:
  ECOFLOW_EMAIL       — EcoFlow app email address
  ECOFLOW_PASSWORD    — EcoFlow app password
  ECOFLOW_WAVE3_SN    — Wave 3 device serial number (e.g. AC71ZK1APJ410297)

Tests auto-skip when credentials are not set.
No write operations are performed — no device state is changed.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.conftest import get_private_email, get_private_password, get_wave3_sn


# ---------------------------------------------------------------------------
# Test: login only — no MQTT connection
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_private_login_succeeds() -> None:
    """login() returns valid PrivateCredentials for the real EcoFlow account.

    Does not open an MQTT connection — verifies auth only.
    If this fails with EcoFlowAuthError, check:
    1. ECOFLOW_EMAIL and ECOFLOW_PASSWORD in tests/.env are correct.
    2. The account exists and can log in to the EcoFlow mobile app.
    3. See auth.py QUIRK comment — password encoding may need updating.
    """
    from ecoflow.private.auth import PrivateCredentials, login

    email = get_private_email()
    password = get_private_password()

    creds = await login(email, password)

    assert isinstance(creds, PrivateCredentials)
    assert len(creds.certificate_account) > 0, "certificate_account must be non-empty"
    assert len(creds.certificate_password) > 0, "certificate_password must be non-empty"
    assert len(creds.user_id) > 0, "user_id must be non-empty"


# ---------------------------------------------------------------------------
# Test: MQTT connects within 15s
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_private_connects() -> None:
    """Wave3Connection connects to MQTT and signals ready within 15s.

    If this times out, check:
    1. mqtt.ecoflow.com:8883 is reachable from your network.
    2. The PrivateCredentials from login() are valid MQTT credentials.
    3. The device SN is correct and belongs to the account.
    """
    from ecoflow.private import Wave3Connection

    email = get_private_email()
    password = get_private_password()
    sn = get_wave3_sn()

    conn = Wave3Connection(email=email, password=password, device_sns=[sn])
    await conn.connect()  # raises TimeoutError if MQTT doesn't connect within 15s

    assert sn in conn.devices, f"Device {sn} not found in conn.devices"
    assert conn._task is not None
    assert not conn._task.done()

    await conn.close()


# ---------------------------------------------------------------------------
# Test: status received within 30s
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_private_receives_status() -> None:
    """Wave3Connection receives status update within 30s.

    After connecting, waits up to 30s for the Wave 3 device to push
    its first status update via MQTT. Verifies key fields are populated
    with non-default values — proving the Protobuf decoder is working.

    If this test times out without status:
    1. The device may be offline or in a low-power state.
    2. The MQTT topic /app/device/property/{sn} may not be publishing.
    3. Check Wave3Device._on_message is calling _handle_message correctly.

    If status fields are all zero / default:
    1. The decoder may be returning {} (wrong cmd_func/cmd_id or XOR key).
    2. Add logging: uv run pytest ... -s and check warning lines in decoder.py.
    """
    from ecoflow.private import Wave3Connection

    email = get_private_email()
    password = get_private_password()
    sn = get_wave3_sn()

    async with Wave3Connection(email=email, password=password, device_sns=[sn]) as conn:
        device = conn.devices[sn]

        # Wait up to 30s for status to arrive via MQTT
        deadline = 30.0
        poll_interval = 0.5
        elapsed = 0.0
        while elapsed < deadline:
            if device.status is not None and device.status.updated_at is not None:
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        else:
            pytest.fail(
                f"No status received for {sn} within {deadline}s. "
                "Check that the device is powered on and the network is reachable."
            )

        status = device.status
        assert status is not None
        assert status.sn == sn
        assert status.online is True
        assert status.updated_at is not None

        # Verify key fields are non-default — proves proto decoding is working.
        # If the device is off, battery_soc and ambient_temp should still be > 0.
        non_default_fields = []
        if status.battery_soc != 0.0:
            non_default_fields.append(f"battery_soc={status.battery_soc:.1f}%")
        if status.ambient_temp != 0.0:
            non_default_fields.append(f"ambient_temp={status.ambient_temp:.1f}°C")
        if status.mode.value != 0:
            non_default_fields.append(f"mode={status.mode.name}")

        assert len(non_default_fields) > 0, (
            f"All key fields are at default values for {sn}. "
            f"battery_soc={status.battery_soc}, ambient_temp={status.ambient_temp}, "
            f"mode={status.mode}. "
            "This suggests the Protobuf decoder returned empty dicts — "
            "check cmd_func/cmd_id dispatch in decoder.py."
        )

        # Log what we received for debugging
        print(f"\nWave 3 status for {sn}:")
        print(f"  is_on={status.is_on}, mode={status.mode.name}")
        print(f"  battery_soc={status.battery_soc:.1f}%")
        print(f"  ambient_temp={status.ambient_temp:.1f}°C")
        print(f"  supply_air_temp={status.supply_air_temp:.1f}°C")
        print(f"  input_power_watts={status.input_power_watts:.1f}W")
        print(f"  non-default fields: {non_default_fields}")
```

**Step 2: Verify tests skip properly without credentials**
```bash
uv run pytest tests/e2e/test_private_read.py -m integration -v
```
Expected: **all 3 tests SKIP** with reason "ECOFLOW_EMAIL not set in tests/.env" — unless you already added real credentials to `tests/.env`.

**Step 3: Run E2E tests with real credentials**

First add your real credentials to `tests/.env` (see Task 4 Step 3). Then:
```bash
uv run pytest tests/e2e/test_private_read.py -m integration -v -s --timeout=60
```

Expected outcomes:
- `test_wave3_private_login_succeeds` — PASS if credentials are correct
- `test_wave3_private_connects` — PASS if Wave 3 device is online and reachable
- `test_wave3_private_receives_status` — PASS if device pushes status within 30s

> **If `test_wave3_private_login_succeeds` fails with `EcoFlowAuthError`:** The password encoding
> assumption (plain text) may be wrong. See the QUIRK comment in `auth.py`. Check if the
> EcoFlow API requires MD5 or base64 encoding. Update `auth.py` and its QUIRK comment if needed.

> **If `test_wave3_private_receives_status` fails with "All key fields are default":**
> The decoder is not recognizing the cmd_func/cmd_id values. Add temporary debug logging to
> `decoder.py` by catching the `{}` return and printing `cmd_func`/`cmd_id` values. Compare
> against tolwi's source. Update the dispatch table if the values differ.

**Step 4: Commit**
```bash
git add tests/e2e/test_private_read.py
git commit -m "test: Wave 3 private API E2E read tests — login, connect, receive_status"
```

---

### Task 6: Write `docs/api/private-authentication.md`

**Files:**
- Create: `docs/api/private-authentication.md`

**Step 1: Create the documentation file**

Create `docs/api/private-authentication.md`:

```markdown
# Private API Authentication (Wave 3)

EcoFlow Wave 3 portable ACs (serial prefix `AC71`) are not supported by the public
EcoFlow Developer API. Any REST query for a Wave 3 device returns error `1006`
("current device is not allowed to get device info").

Use `Wave3Connection` from `ecoflow.private` instead. It authenticates with your
EcoFlow **app email and password** to obtain private MQTT credentials.

## Installation

```bash
pip install ecoflow-python[wave3]
```

The `[wave3]` extra installs the `protobuf>=4.0` package required to decode Wave 3
Protobuf payloads. Without it, importing `ecoflow.private` raises a clear `ImportError`.

## Quick start

```python
import asyncio
from ecoflow.private import Wave3Connection

async def main() -> None:
    async with Wave3Connection(
        email="me@example.com",     # your EcoFlow app login email
        password="my_password",     # your EcoFlow app login password
        device_sns=["AC71ZK1APJ410297"],
    ) as wave3:
        device = wave3.devices["AC71ZK1APJ410297"]
        await asyncio.sleep(10)    # wait for first MQTT status push
        status = device.status
        print(f"Battery: {status.battery_soc:.0f}%")
        print(f"Mode: {status.mode.name}")
        print(f"Temperature: {status.ambient_temp:.1f}°C")

asyncio.run(main())
```

## How it works

1. `Wave3Connection.connect()` calls `POST https://api.ecoflow.com/auth/login` with
   your email and password.
2. The response contains `certificateAccount` (MQTT username) and `certificatePassword`
   (MQTT password). These are long-lived credentials — no refresh is needed in normal use.
3. An `aiomqtt.Client` connects to `mqtt.ecoflow.com:8883` (TLS) using these credentials.
4. The client subscribes to `/app/device/property/{sn}` for each device SN at QoS 1.
5. Incoming messages are Protobuf-encoded and may be XOR-encrypted. The decoder reverses
   this and returns a flat `dict[str, Any]` keyed by proto field names.
6. The dict is forwarded to `Wave3Device._handle_message()`, which updates `device.status`.

## Credentials vs Developer API

| | Private API (Wave 3) | Public Developer API |
|---|---|---|
| Auth input | EcoFlow app email + password | `accessKey` + `secretKey` |
| Where to get | Your mobile app login | developer.ecoflow.com |
| MQTT broker | `mqtt.ecoflow.com` | `mqtt-e.ecoflow.com` (EU) |
| Wave 3 support | ✅ | ❌ (error 1006) |
| Other devices | ❌ (use `EcoFlowClient`) | ✅ |

The two APIs are independent. You can use both simultaneously in the same program.

## Security note

Treat your EcoFlow app password as a secret. Store it in environment variables or a
`.env` file — never commit it to version control. The `tests/.env` file in this repo
is gitignored for this reason.

## Regions

The private API endpoint (`api.ecoflow.com`) and broker (`mqtt.ecoflow.com`) are
global — the same URL works for EU and US accounts. Do not use the EU-regional
broker `mqtt-e.ecoflow.com` for the private API.

## Reconnection

If the MQTT connection drops, `Wave3Connection` reconnects automatically with
exponential backoff: 1s → 2s → 4s → … → 300s cap. The `device.status` retains the
last known state between disconnects.

## Open questions / known limitations

- **Write commands** are not yet implemented. Setting temperature, mode, or fan speed
  via the private API requires Protobuf command encoding (deferred to a future release).
  Use the public `EcoFlowClient` for write commands on supported devices.
- **Token expiry** — private credentials appear long-lived, but expiry behaviour is
  undocumented. A re-login flow can be added when/if expiry is observed in practice.
- **Other devices** — Wave 2 and other devices excluded from the public API may follow
  a similar protocol. Not confirmed; Wave 3 is the only device tested with this client.
```

**Step 2: Commit**
```bash
git add docs/api/private-authentication.md
git commit -m "docs: private-authentication.md — Wave 3 private API user guide"
```

---

### Task 7: Final test suite run and Phase 2 commit

**Step 1: Run the complete non-integration test suite**
```bash
uv run pytest -m "not integration and not write_integration" -q
```
Expected: **all tests pass**. Zero failures, zero errors.

If failures appear:
- `ImportError: cannot import name 'Wave3Connection' from 'ecoflow'` → check `src/ecoflow/__init__.py` try/except block
- `AssertionError: Missing: {'Wave3Connection'}` in `test_all_list_contains_expected_symbols` → `"Wave3Connection"` was not added to `expected` in `test_toplevel_exports.py`
- `AttributeError` on `Wave3Mode.COOL` → a reference to the old enum survived; search with `grep -r "Wave3Mode\.COOL" tests/ src/`

**Step 2: Run a lint check**
```bash
uv run ruff check src/ecoflow/private/ tests/test_private_*.py --fix
```
Expected: no issues.

**Step 3: Run the E2E integration tests** (requires `tests/.env` with real credentials)
```bash
uv run pytest tests/e2e/test_private_read.py -m integration -v -s --timeout=60
```
Expected:
- All 3 tests PASS if credentials are correct and Wave 3 device is online.
- All 3 tests SKIP if `tests/.env` credentials are not set.

> **If `test_wave3_private_login_succeeds` fails:** The password may need encoding.
> Try MD5: `import hashlib; password = hashlib.md5(password.encode()).hexdigest()`
> Update `auth.py` and its QUIRK comment accordingly.

**Step 4: Final Phase 2 commit**
```bash
git add -A
git commit -m "feat: Wave 3 Phase 2 complete — Wave3Connection, private exports, E2E tests, docs"
```

---

## Phase 2 completion checklist

Before declaring the implementation complete, verify all of these:

- [ ] `from ecoflow.private import Wave3Connection` — no error
- [ ] `from ecoflow import Wave3Connection` — no error (requires protobuf installed)
- [ ] `uv run pytest -m "not integration and not write_integration" -q` — all PASS
- [ ] `uv run pytest tests/e2e/test_private_read.py -m integration -v -s --timeout=60` — all PASS or SKIP
- [ ] `docs/api/private-authentication.md` exists
- [ ] `tests/.env.example` documents `ECOFLOW_EMAIL`, `ECOFLOW_PASSWORD`, `ECOFLOW_WAVE3_SN`
- [ ] No `@pytest.mark.write_integration` tests exist in the private API test files
- [ ] The existing `EcoFlowClient` is unchanged (confirm with `git diff src/ecoflow/client.py`)

---

## Architecture summary (what you built across both phases)

```
ecoflow/
├── private/                        ← NEW subpackage
│   ├── __init__.py                 exports Wave3Connection
│   ├── auth.py                     login(email, password) → PrivateCredentials
│   ├── connection.py               Wave3Connection async context manager
│   └── proto/
│       ├── __init__.py
│       ├── wave3_pb2.py            vendored (tolwi MIT, do not edit)
│       └── decoder.py              decode(bytes) → dict[str, Any]
│
├── models/wave3.py                 UPDATED — Wave3Mode + Wave3Status (proto fields)
├── devices/wave3.py                UPDATED — refresh() handles rest=None
└── __init__.py                     UPDATED — exports Wave3Connection

Data flow for a status update:
  MQTT → Wave3Connection._run()
       → decode(raw_bytes)          XOR decrypt + proto parse → flat dict
       → Wave3Device._handle_message(sn, data)
       → Wave3Device._on_message()
       → Wave3Status.from_mqtt_payload(sn, data)
       → device.status (available to caller)
```
