"""Unit tests for Wave3Connection lifecycle.

Tests connect/close/context-manager using mocked login() and mocked _run().
No real network calls — no credentials required.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------------------------------------------------------------------------
# connect() — stores _user_id after login
# ---------------------------------------------------------------------------


async def test_connect_stores_user_id() -> None:
    """connect() stores creds.user_id in self._user_id after login."""
    conn = _make_conn("AC71TEST001")
    p_login = patch(_LOGIN_PATH, new=AsyncMock(return_value=FAKE_CREDS))
    p_run = patch.object(conn, "_run", side_effect=_make_run_se(conn))
    with p_login, p_run:
        await conn.connect()

    assert conn._user_id == FAKE_CREDS.user_id  # "987654"

    await conn.close()


# ---------------------------------------------------------------------------
# _run() — GET trigger published after subscribe
# ---------------------------------------------------------------------------


def _make_mock_aiomqtt_client() -> tuple[MagicMock, list[tuple[str, bytes]]]:
    """Build a mock aiomqtt.Client that records publish calls.

    Returns (client_mock, published_list) where published_list accumulates
    (topic, payload) tuples for every publish() call.
    The client's .messages async-generator blocks forever (never yields a
    message) so _receive_loop stays idle until the task is cancelled.
    """
    published: list[tuple[str, bytes]] = []

    async def _fake_publish(topic: str, payload: bytes, *, qos: int = 0) -> None:
        published.append((topic, bytes(payload)))

    async def _never_yield():  # pragma: no cover
        await asyncio.sleep(1_000)
        if False:  # noqa: SIM210
            yield  # makes it an async generator

    mock_client = MagicMock()
    mock_client.subscribe = AsyncMock()
    mock_client.publish = AsyncMock(side_effect=_fake_publish)
    mock_client.messages = _never_yield()

    return mock_client, published


async def test_run_publishes_get_trigger_after_subscribe() -> None:
    """_run() publishes a JSON GET payload to /app/{user_id}/{sn}/thing/property/get
    for every device SN immediately after the subscribe loop."""
    conn = Wave3Connection(
        email="test@example.com",
        password="test_pass",
        device_sns=["SN_ALPHA"],
    )
    conn.devices = {
        "SN_ALPHA": Wave3Device(sn="SN_ALPHA", product_name="Wave 3", rest=None),
    }

    mock_client, published = _make_mock_aiomqtt_client()

    # Wrap mock_client in an async context manager (async with aiomqtt.Client(...) as c)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    creds = PrivateCredentials(
        certificate_account="acct",
        certificate_password="pwd",
        user_id="USER42",
    )

    with patch("ecoflow.private.connection.aiomqtt.Client", return_value=mock_cm):
        task = asyncio.create_task(conn._run(creds))
        await asyncio.sleep(0.05)  # let _run() reach subscribe + GET publish
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    expected_topic = "/app/USER42/SN_ALPHA/thing/property/get"
    topics = [t for t, _ in published]
    assert expected_topic in topics, f"GET trigger not published; got: {topics}"

    # Verify payload structure
    for topic, payload in published:
        if topic == expected_topic:
            data = json.loads(payload)
            assert data["operateType"] == "get"
            assert data["sn"] == "SN_ALPHA"
            assert data["version"] == "1.0"


async def test_run_publishes_get_trigger_for_each_device() -> None:
    """_run() publishes a GET trigger for every device in self.devices."""
    sns = ["SN_ONE", "SN_TWO", "SN_THREE"]
    conn = Wave3Connection(
        email="test@example.com",
        password="test_pass",
        device_sns=sns,
    )
    conn.devices = {
        sn: Wave3Device(sn=sn, product_name="Wave 3", rest=None) for sn in sns
    }

    mock_client, published = _make_mock_aiomqtt_client()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    creds = PrivateCredentials(
        certificate_account="acct",
        certificate_password="pwd",
        user_id="USERXYZ",
    )

    with patch("ecoflow.private.connection.aiomqtt.Client", return_value=mock_cm):
        task = asyncio.create_task(conn._run(creds))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    published_topics = {t for t, _ in published}
    for sn in sns:
        expected = f"/app/USERXYZ/{sn}/thing/property/get"
        assert expected in published_topics, f"Missing GET trigger for {sn}"
