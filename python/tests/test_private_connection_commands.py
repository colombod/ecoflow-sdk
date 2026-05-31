"""Unit tests for Wave3Connection publish queue and write command methods.

Tests the asyncio.Queue-backed publish loop interface and ten high-level
command methods without real MQTT — no credentials required.
"""

from __future__ import annotations

import pytest

from ecoflow.devices.wave3 import Wave3Device
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.models.wave3 import Wave3Mode
from ecoflow.private.connection import Wave3Connection
from ecoflow.private.proto import wave3_pb2

_SN = "AC71ZTEST001"


def _make_conn(sn: str = _SN) -> Wave3Connection:
    """Build a Wave3Connection with one device pre-loaded, no real MQTT."""
    conn = Wave3Connection(
        email="test@example.com",
        password="test_pass",
        device_sns=[sn],
    )
    conn.devices = {sn: Wave3Device(sn=sn, product_name="Wave 3", rest=None)}
    return conn


def _decode_config_write(payload: bytes) -> wave3_pb2.Wave3ConfigWrite:  # type: ignore[name-defined]
    """Parse the Wave3ConfigWrite inner message from a Wave3SetMessage payload."""
    msg = wave3_pb2.Wave3SetMessage()  # type: ignore[attr-defined]
    msg.ParseFromString(payload)
    inner = wave3_pb2.Wave3ConfigWrite()  # type: ignore[attr-defined]
    inner.ParseFromString(msg.header.pdata)
    return inner


# ---------------------------------------------------------------------------
# send_raw — connection guard and SN validation
# ---------------------------------------------------------------------------


async def test_send_raw_raises_when_not_connected() -> None:
    """send_raw raises EcoFlowConnectionError when _ready is not set."""
    conn = _make_conn()
    # _ready is a fresh asyncio.Event — not set by default
    assert not conn._ready.is_set()

    with pytest.raises(EcoFlowConnectionError):
        await conn.send_raw(_SN, b"payload")


async def test_send_raw_raises_for_unknown_sn() -> None:
    """send_raw raises ValueError for an SN not in conn.devices."""
    conn = _make_conn()
    conn._ready.set()

    with pytest.raises(ValueError, match="UNKNOWN"):
        await conn.send_raw("UNKNOWN", b"payload")


# ---------------------------------------------------------------------------
# turn_on / turn_off — queue payload verification
# ---------------------------------------------------------------------------


async def test_turn_on_publishes_main_power_true() -> None:
    """turn_on() puts a payload on the queue with cfg_main_power=True."""
    conn = _make_conn()
    conn._ready.set()

    await conn.turn_on(_SN)

    sn_queued, payload = conn._publish_queue.get_nowait()
    assert sn_queued == _SN
    inner = _decode_config_write(payload)
    assert inner.cfg_main_power is True


async def test_turn_off_publishes_sys_pause() -> None:
    """turn_off() puts a payload on the queue with cfg_sys_pause=True."""
    conn = _make_conn()
    conn._ready.set()

    await conn.turn_off(_SN)

    sn_queued, payload = conn._publish_queue.get_nowait()
    assert sn_queued == _SN
    inner = _decode_config_write(payload)
    assert inner.cfg_sys_pause is True


# ---------------------------------------------------------------------------
# set_mode — mode validation and payload
# ---------------------------------------------------------------------------


async def test_set_mode_cooling_publishes_correct_mode() -> None:
    """set_mode(COOLING) publishes cfg_wave_operating_mode==1."""
    conn = _make_conn()
    conn._ready.set()

    await conn.set_mode(_SN, Wave3Mode.COOLING)

    _, payload = conn._publish_queue.get_nowait()
    inner = _decode_config_write(payload)
    assert inner.cfg_wave_operating_mode == 1


async def test_set_mode_none_raises() -> None:
    """set_mode(NONE) raises ValueError mentioning 'turn_off'."""
    conn = _make_conn()
    conn._ready.set()

    with pytest.raises(ValueError, match="turn_off"):
        await conn.set_mode(_SN, Wave3Mode.NONE)


# ---------------------------------------------------------------------------
# set_temperature — range validation
# ---------------------------------------------------------------------------


async def test_set_temperature_valid_range() -> None:
    """set_temperature accepts 16.0 and 30.0, rejects 15.9 and 30.1."""
    conn = _make_conn()
    conn._ready.set()

    # Valid boundary values — must not raise
    await conn.set_temperature(_SN, 16.0)
    await conn.set_temperature(_SN, 30.0)

    # Invalid values — must raise ValueError
    with pytest.raises(ValueError):
        await conn.set_temperature(_SN, 15.9)

    with pytest.raises(ValueError):
        await conn.set_temperature(_SN, 30.1)


# ---------------------------------------------------------------------------
# set_fan_speed — level mapping and range validation
# ---------------------------------------------------------------------------


async def test_set_fan_speed_maps_levels() -> None:
    """set_fan_speed maps levels 1→20, 3→60, 5→100 in the payload."""
    conn = _make_conn()
    conn._ready.set()

    # Level 1 → raw 20
    await conn.set_fan_speed(_SN, 1)
    _, payload = conn._publish_queue.get_nowait()
    assert _decode_config_write(payload).cfg_airflow_speed == 20

    # Level 3 → raw 60
    await conn.set_fan_speed(_SN, 3)
    _, payload = conn._publish_queue.get_nowait()
    assert _decode_config_write(payload).cfg_airflow_speed == 60

    # Level 5 → raw 100
    await conn.set_fan_speed(_SN, 5)
    _, payload = conn._publish_queue.get_nowait()
    assert _decode_config_write(payload).cfg_airflow_speed == 100

    # Out-of-range values must raise ValueError
    with pytest.raises(ValueError):
        await conn.set_fan_speed(_SN, 0)

    with pytest.raises(ValueError):
        await conn.set_fan_speed(_SN, 6)


# ---------------------------------------------------------------------------
# set_humidity_target — range validation
# ---------------------------------------------------------------------------


async def test_set_humidity_range() -> None:
    """set_humidity_target accepts 40.0 and 80.0, rejects 39.9 and 80.1."""
    conn = _make_conn()
    conn._ready.set()

    await conn.set_humidity_target(_SN, 40.0)
    await conn.set_humidity_target(_SN, 80.0)

    with pytest.raises(ValueError):
        await conn.set_humidity_target(_SN, 39.9)

    with pytest.raises(ValueError):
        await conn.set_humidity_target(_SN, 80.1)


# ---------------------------------------------------------------------------
# set_charge_limit — range validation
# ---------------------------------------------------------------------------


async def test_set_charge_limit_range() -> None:
    """set_charge_limit accepts 50–100, rejects 49 and 101."""
    conn = _make_conn()
    conn._ready.set()

    await conn.set_charge_limit(_SN, 50)
    await conn.set_charge_limit(_SN, 100)

    with pytest.raises(ValueError):
        await conn.set_charge_limit(_SN, 49)

    with pytest.raises(ValueError):
        await conn.set_charge_limit(_SN, 101)


# ---------------------------------------------------------------------------
# set_discharge_limit — range validation
# ---------------------------------------------------------------------------


async def test_set_discharge_limit_range() -> None:
    """set_discharge_limit accepts 0–30, rejects -1 and 31."""
    conn = _make_conn()
    conn._ready.set()

    await conn.set_discharge_limit(_SN, 0)
    await conn.set_discharge_limit(_SN, 30)

    with pytest.raises(ValueError):
        await conn.set_discharge_limit(_SN, -1)

    with pytest.raises(ValueError):
        await conn.set_discharge_limit(_SN, 31)
