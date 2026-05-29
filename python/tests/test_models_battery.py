"""Tests for battery device models.

Covers BmsModule, ExpansionBatteryModule, SolarInput, and BatteryStatus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecoflow.models.battery import BatteryStatus, BmsModule

VECTORS_DIR = Path(__file__).parent / "vectors"


def load_vector(device: str, name: str) -> tuple[dict, dict]:
    """Load a test vector pair (payload + expected) for a device."""
    base = VECTORS_DIR / device
    payload = json.loads((base / f"{name}.json").read_text())
    expected = json.loads((base / f"{name}.expected.json").read_text())
    return payload, expected


def test_bms_module_parses_voltage_from_mv() -> None:
    """BmsModule.from_mqtt_payload converts raw mV/mA/temp values correctly."""
    data = {
        "vol": 51200,
        "amp": -5000,
        "temp": 280,
        "soc": 85,
        "cycles": 42,
        "designCap": 102400,
        "fullCap": 98000,
        "remainCap": 83300,
        "soh": 96,
        "minCellTemp": 270,
        "maxCellTemp": 290,
        "minCellVol": 3200,
        "maxCellVol": 3250,
    }
    bms = BmsModule.from_mqtt_payload(data)
    assert bms.voltage == pytest.approx(51.2)
    assert bms.current == pytest.approx(-5.0)
    assert bms.temp == pytest.approx(28.0)
    assert bms.soc == 85


def test_battery_status_from_vector() -> None:
    """BatteryStatus.from_mqtt_payload maps vector payload to expected fields."""
    payload, expected = load_vector("battery", "payload_status")
    status = BatteryStatus.from_mqtt_payload("SN12345", payload)
    assert status.soc == expected["soc"]
    assert (
        status.remaining_discharge_time_min == expected["remaining_discharge_time_min"]
    )
    assert status.ac_output_watts == expected["ac_output_watts"]
    assert status.ac_output_enabled == expected["ac_output_enabled"]


def test_battery_status_has_sn() -> None:
    """BatteryStatus.from_mqtt_payload preserves sn and defaults soc to 0.0."""
    status = BatteryStatus.from_mqtt_payload("SN99999", {})
    assert status.sn == "SN99999"
    assert status.soc == 0.0
