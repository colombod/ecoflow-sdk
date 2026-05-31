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

_LOGIN_PATH = "ecoflow.private.connection.login"


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


def _make_run_se(conn: Wave3Connection):
    """Return a coroutine-function side_effect for patching _run on an instance.

    Python 3.13 AsyncMock only awaits side_effects that are coroutine functions.
    A lambda returning a coroutine is NOT a coroutine function — its result would
    be returned without awaiting, leaving _ready unset.  This factory wraps
    _fake_run in an async def so iscoroutinefunction() returns True.
    """

    async def _se(creds: PrivateCredentials) -> None:
        await _fake_run(conn, creds)

    return _se


# ---------------------------------------------------------------------------
# Construction — devices dict is empty before connect()
# ---------------------------------------------------------------------------


def test_devices_empty_before_connect() -> None:
    """Wave3Connection.devices is empty dict before connect() is called."""
    conn = _make_conn("AC71TEST001")
    assert conn.devices == {}


def test_construction_does_not_call_login() -> None:
    """Creating Wave3Connection does not trigger any network calls."""
    with patch(_LOGIN_PATH) as mock_login:
        _make_conn("AC71TEST001")
    mock_login.assert_not_called()


# ---------------------------------------------------------------------------
# connect() — devices populated, task started
# ---------------------------------------------------------------------------


async def test_connect_populates_devices_dict() -> None:
    """connect() populates devices dict with one Wave3Device per SN."""
    conn = _make_conn("AC71TEST001", "AC71TEST002")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
        await conn.connect()

    assert "AC71TEST001" in conn.devices
    assert "AC71TEST002" in conn.devices

    await conn.close()


async def test_connect_creates_wave3_device_instances() -> None:
    """Each device in conn.devices is a Wave3Device with rest=None."""
    conn = _make_conn("AC71TEST001")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
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
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with patch(_LOGIN_PATH, new=mock_login), p_run:
        await conn.connect()

    mock_login.assert_called_once_with("test@example.com", "test_pass")

    await conn.close()


# ---------------------------------------------------------------------------
# close() — background task cancelled
# ---------------------------------------------------------------------------


async def test_close_cancels_background_task() -> None:
    """close() cancels the background MQTT task."""
    conn = _make_conn("AC71TEST001")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
        await conn.connect()

    task = conn._task
    assert task is not None
    assert not task.done()

    await conn.close()

    assert task.done()


async def test_close_is_idempotent() -> None:
    """Calling close() twice does not raise."""
    conn = _make_conn("AC71TEST001")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
        await conn.connect()

    await conn.close()
    await conn.close()  # second call — must not raise


# ---------------------------------------------------------------------------
# Context manager — __aenter__ / __aexit__
# ---------------------------------------------------------------------------


async def test_context_manager_calls_connect_and_close() -> None:
    """async with Wave3Connection(...) calls connect() then close()."""
    conn = _make_conn("AC71TEST001")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
        async with conn:
            assert "AC71TEST001" in conn.devices

    # After exiting the context, task should be done
    assert conn._task is None or conn._task.done()


async def test_context_manager_returns_self() -> None:
    """'as' clause in async with receives the Wave3Connection instance."""
    conn = _make_conn("AC71TEST001")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
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

    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_run_that_never_signals)
    p_timeout = patch("ecoflow.private.connection._CONNECT_TIMEOUT_S", 0.05)
    with p_login, p_run, p_timeout:
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await conn.connect()
