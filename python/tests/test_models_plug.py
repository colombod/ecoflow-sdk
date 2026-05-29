"""Tests for SmartPlugData model.

Covers the WATTS_RAW_FACTOR quirk (3-place rule), from_mqtt_payload with a
hard-coded heartbeat payload, and from_quota_payload with the real REST vector.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ecoflow.models.plug import WATTS_RAW_FACTOR, SmartPlugData

VECTORS_DIR = Path(__file__).parent / "vectors"


def load_vector(device: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a test vector pair (payload + expected) for a device."""
    base = VECTORS_DIR / device
    payload: dict[str, Any] = json.loads((base / f"{name}.json").read_text())
    expected: dict[str, Any] = json.loads(
        (base / f"{name}.expected.json").read_text()
    )
    return payload, expected


def test_watts_raw_factor_is_documented() -> None:
    """WATTS_RAW_FACTOR is 0.1 — raw 'watts' field is 10× actual wattage.

    QUIRK: Smart Plug firmware v1.x (confirmed 2024-11) sends watts as integer
    tenths of a watt. raw=2640 → actual=264.0 W.
    If this test fails, the firmware patched the scaling factor.
    """
    assert WATTS_RAW_FACTOR == 0.1


def test_smart_plug_from_quota_vector() -> None:
    """SmartPlugData.from_quota_payload maps the quota/all vector to expected fields.

    Vector confirmed from live HW52-series Smart Plug device, 2026-05.
    Uses flat '2_1.*' key format returned by the real /quota/all endpoint.
    """
    payload, expected = load_vector("smart_plug", "payload_power")
    plug = SmartPlugData.from_quota_payload("SP12345", payload)

    assert plug.is_on == expected["is_on"]
    assert plug.power_watts == pytest.approx(expected["power_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert plug.voltage == pytest.approx(expected["voltage"])  # pyright: ignore[reportUnknownMemberType]
    assert plug.current == pytest.approx(expected["current"])  # pyright: ignore[reportUnknownMemberType]
    assert plug.temp == pytest.approx(expected["temp"])  # pyright: ignore[reportUnknownMemberType]
    assert plug.brightness == expected["brightness"]


def test_smart_plug_off_state() -> None:
    """SmartPlugData.from_mqtt_payload sets is_on=False and power_watts=0.0 when off.

    The MQTT heartbeat path still uses plug_heartbeat format.
    """
    payload = {"plug_heartbeat": {"plugState": 0, "watts": 0}}
    plug = SmartPlugData.from_mqtt_payload("SP00000", payload)

    assert plug.is_on is False
    assert plug.power_watts == 0.0


def test_smart_plug_quota_brightness_full_scale() -> None:
    """from_quota_payload converts 10-bit brightness (1023) → 100 %."""
    payload: dict[str, Any] = {"2_1.brightness": 1023}
    plug = SmartPlugData.from_quota_payload("SP00001", payload)
    assert plug.brightness == 100


def test_smart_plug_quota_brightness_zero() -> None:
    """from_quota_payload treats brightness=0 as 0 %."""
    payload: dict[str, Any] = {"2_1.brightness": 0}
    plug = SmartPlugData.from_quota_payload("SP00001", payload)
    assert plug.brightness == 0


def test_smart_plug_quota_voltage_no_factor() -> None:
    """from_quota_payload: volt is already in Volts — no 0.1 factor applied.

    QUIRK: REST quota/all 'volt' field differs from MQTT 'vol' field.
    MQTT: raw=2300 → 230 V (×0.1 factor).
    REST: raw=242  → 242 V (no factor — already in Volts).
    """
    payload: dict[str, Any] = {"2_1.volt": 242}
    plug = SmartPlugData.from_quota_payload("SP00002", payload)
    assert plug.voltage == pytest.approx(242.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_plug_quota_temp_no_factor() -> None:
    """from_quota_payload: temp is already in °C — no /10 factor applied.

    QUIRK: REST quota/all 'temp' field differs from MQTT 'temp' field.
    MQTT: raw=380 → 38.0 °C (/10 factor).
    REST: raw=36  → 36.0 °C (no factor — already in °C).
    """
    payload: dict[str, Any] = {"2_1.temp": 36}
    plug = SmartPlugData.from_quota_payload("SP00002", payload)
    assert plug.temp == pytest.approx(36.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_plug_quota_current_milliamps_to_amps() -> None:
    """from_quota_payload: current field is in mA — converted to A by /1000."""
    payload: dict[str, Any] = {"2_1.current": 1598}
    plug = SmartPlugData.from_quota_payload("SP00002", payload)
    assert plug.current == pytest.approx(1.598)  # pyright: ignore[reportUnknownMemberType]
