"""Tests for SmartMeterData model — real BK21 MQTT field names confirmed 2026-05-29."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ecoflow.models.meter import SmartMeterData

VECTORS_DIR = Path(__file__).parent / "vectors"


def load_vector(device: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a test vector pair (payload + expected) for a device."""
    base = VECTORS_DIR / device
    payload: dict[str, Any] = json.loads((base / f"{name}.json").read_text())
    expected: dict[str, Any] = json.loads((base / f"{name}.expected.json").read_text())
    return payload, expected


# ---------------------------------------------------------------------------
# Vector-based test (real MQTT data from BK21Z1BB7H414753)
# ---------------------------------------------------------------------------


def test_smart_meter_from_quota_vector() -> None:
    """SmartMeterData.from_quota_payload maps the real MQTT vector to expected fields.

    Real data from live device BK21Z1BB7H414753, confirmed 2026-05-29.
    """
    payload, expected = load_vector("smart_meter", "payload_status")
    meter = SmartMeterData.from_quota_payload("BK21Z1BB7H414753", payload)

    assert meter.grid_power_watts == pytest.approx(expected["grid_power_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert meter.grid_status == expected["grid_status"]
    assert meter.voltage_l1 == pytest.approx(expected["voltage_l1"])  # pyright: ignore[reportUnknownMemberType]
    assert meter.power_l1 == pytest.approx(expected["power_l1"])  # pyright: ignore[reportUnknownMemberType]
    assert meter.current_l1 == pytest.approx(expected["current_l1"])  # pyright: ignore[reportUnknownMemberType]
    assert meter.phase_l1_active is expected["phase_l1_active"]
    assert meter.phase_l2_active is expected["phase_l2_active"]
    assert meter.total_active_energy_wh == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        expected["total_active_energy_wh"]
    )


# ---------------------------------------------------------------------------
# Unit tests for individual fields
# ---------------------------------------------------------------------------


def test_smart_meter_system_grid_power() -> None:
    """powGetSysGrid maps to grid_power_watts."""
    meter = SmartMeterData.from_quota_payload("BK21", {"powGetSysGrid": 4917.057})
    assert meter.grid_power_watts == pytest.approx(4917.057)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_grid_status_string() -> None:
    """gridConnectionSta maps to grid_status as a string."""
    meter = SmartMeterData.from_quota_payload(
        "BK21", {"gridConnectionSta": "PANEL_GRID_IN"}
    )
    assert meter.grid_status == "PANEL_GRID_IN"


def test_smart_meter_phase_voltages() -> None:
    """gridConnectionVolL1/L2/L3 map to voltage_l1/l2/l3."""
    payload = {
        "gridConnectionVolL1": 237.38,
        "gridConnectionVolL2": 118.39,
        "gridConnectionVolL3": 118.40,
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.voltage_l1 == pytest.approx(237.38)  # pyright: ignore[reportUnknownMemberType]
    assert meter.voltage_l2 == pytest.approx(118.39)  # pyright: ignore[reportUnknownMemberType]
    assert meter.voltage_l3 == pytest.approx(118.40)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_phase_powers() -> None:
    """gridConnectionPowerL1/L2/L3 map to power_l1/l2/l3."""
    payload = {
        "gridConnectionPowerL1": 4917.06,
        "gridConnectionPowerL2": 0.0,
        "gridConnectionPowerL3": 0.0,
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.power_l1 == pytest.approx(4917.06)  # pyright: ignore[reportUnknownMemberType]
    assert meter.power_l2 == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]
    assert meter.power_l3 == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_phase_currents() -> None:
    """gridConnectionAmpL1/L2/L3 map to current_l1/l2/l3."""
    payload = {"gridConnectionAmpL1": 21.61, "gridConnectionAmpL2": 0.0}
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.current_l1 == pytest.approx(21.61)  # pyright: ignore[reportUnknownMemberType]
    assert meter.current_l2 == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_phase_flags() -> None:
    """gridConnectionFlagL1/L2/L3 map to phase_l1/l2/l3_active booleans."""
    payload = {
        "gridConnectionFlagL1": True,
        "gridConnectionFlagL2": False,
        "gridConnectionFlagL3": False,
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.phase_l1_active is True
    assert meter.phase_l2_active is False
    assert meter.phase_l3_active is False


def test_smart_meter_energy_totals() -> None:
    """gridConnectionDataRecord nested dict maps to energy total fields.

    RENAME NOTE: total_reactive_energy_varh → total_exported_energy_wh.
    EcoFlow misnames exported energy as 'totalReactiveEnergy'.
    """
    payload = {
        "gridConnectionDataRecord": {
            "totalActiveEnergy": 9068059.0,
            "todayActive": 9076453.0,
            "totalReactiveEnergy": 8394.0,
        }
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.total_active_energy_wh == pytest.approx(9068059.0)  # pyright: ignore[reportUnknownMemberType]
    assert meter.today_active_energy_wh == pytest.approx(9076453.0)  # pyright: ignore[reportUnknownMemberType]
    assert meter.total_exported_energy_wh == pytest.approx(8394.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_power_factor() -> None:
    """gridConnectionPowerFactor maps to power_factor."""
    meter = SmartMeterData.from_quota_payload(
        "BK21", {"gridConnectionPowerFactor": 0.95}
    )
    assert meter.power_factor == pytest.approx(0.95)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_sn_stored() -> None:
    """from_quota_payload stores the SN on the object."""
    meter = SmartMeterData.from_quota_payload("BK21TESTDEV", {})
    assert meter.sn == "BK21TESTDEV"


def test_smart_meter_online_true() -> None:
    """from_quota_payload marks device as online=True."""
    meter = SmartMeterData.from_quota_payload("BK21", {})
    assert meter.online is True


def test_smart_meter_defaults_zero_when_empty() -> None:
    """Empty payload yields zero defaults for numeric fields."""
    meter = SmartMeterData.from_quota_payload("BK21", {})
    assert meter.grid_power_watts == 0.0
    assert meter.voltage_l1 == 0.0
    assert meter.power_l1 == 0.0
    assert meter.total_active_energy_wh == 0.0


def test_smart_meter_updated_at_is_set() -> None:
    """from_quota_payload sets updated_at to a non-None datetime."""
    meter = SmartMeterData.from_quota_payload("BK21", {})
    assert meter.updated_at is not None


def test_smart_meter_from_mqtt_payload_alias() -> None:
    """from_mqtt_payload is an alias for from_quota_payload (backward compat)."""
    meter = SmartMeterData.from_mqtt_payload("BK21", {"powGetSysGrid": 100.0})
    assert meter.grid_power_watts == pytest.approx(100.0)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Step 5 new tests: total_exported_energy_wh (renamed), per-phase lifetime
# ---------------------------------------------------------------------------


def test_smart_meter_total_exported_energy_wh_renamed() -> None:
    """totalReactiveEnergy maps to total_exported_energy_wh (renamed from varh).

    QUIRK: EcoFlow misnames this field 'totalReactiveEnergy' but it measures
    lifetime exported Wh. Confirmed by tolwi/hassio-ecoflow-cloud research 2026-05-29.
    """
    payload = {
        "gridConnectionDataRecord": {
            "totalReactiveEnergy": 8394.0,
        }
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.total_exported_energy_wh == pytest.approx(8394.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_lifetime_energy_l1() -> None:
    """todayActiveL1 → lifetime_energy_l1_wh (QUIRK: EcoFlow misnames as 'today')."""
    payload = {
        "gridConnectionDataRecord": {
            "todayActiveL1": 3123456.0,
        }
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.lifetime_energy_l1_wh == pytest.approx(3123456.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_lifetime_energy_l2() -> None:
    """todayActiveL2 maps to lifetime_energy_l2_wh."""
    payload = {
        "gridConnectionDataRecord": {
            "todayActiveL2": 1234567.0,
        }
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.lifetime_energy_l2_wh == pytest.approx(1234567.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_lifetime_energy_l3() -> None:
    """todayActiveL3 maps to lifetime_energy_l3_wh."""
    payload = {
        "gridConnectionDataRecord": {
            "todayActiveL3": 987654.0,
        }
    }
    meter = SmartMeterData.from_quota_payload("BK21", payload)
    assert meter.lifetime_energy_l3_wh == pytest.approx(987654.0)  # pyright: ignore[reportUnknownMemberType]


def test_smart_meter_lifetime_energy_defaults_zero() -> None:
    """Per-phase lifetime energy fields default to 0.0 when absent."""
    meter = SmartMeterData.from_quota_payload("BK21", {})
    assert meter.lifetime_energy_l1_wh == 0.0
    assert meter.lifetime_energy_l2_wh == 0.0
    assert meter.lifetime_energy_l3_wh == 0.0
    assert meter.total_exported_energy_wh == 0.0
