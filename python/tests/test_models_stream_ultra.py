"""Tests for StreamUltraStatus model (STREAM Ultra and STREAM AC Pro).

Covers from_quota_payload() with real MQTT vectors confirmed from live devices
BK11ZK1B2H5S1478 (STREAM Ultra master) and BK31 (STREAM AC Pro slave), 2026-05-29.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

VECTORS_DIR = Path(__file__).parent / "vectors"


def load_vector(device: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a test vector pair (payload + expected) for a device."""
    base = VECTORS_DIR / device
    payload: dict[str, Any] = json.loads((base / f"{name}.json").read_text())
    expected: dict[str, Any] = json.loads((base / f"{name}.expected.json").read_text())
    return payload, expected


def test_stream_ultra_from_quota_vector() -> None:
    """StreamUltraStatus.from_quota_payload maps the real MQTT vector to expected.

    Real data from live device BK11ZK1B2H5S1478, confirmed 2026-05-29.
    """
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload, expected = load_vector("stream_ultra", "payload_status")
    status = StreamUltraStatus.from_quota_payload("BK11ZK1B2H5S1478", payload)

    assert status.batt_soc == pytest.approx(expected["batt_soc"])  # pyright: ignore[reportUnknownMemberType]
    assert status.cascade_soc == expected["cascade_soc"]
    assert status.grid_power_watts == pytest.approx(expected["grid_power_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert status.load_power_watts == pytest.approx(expected["load_power_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert status.battery_power_watts == pytest.approx(expected["battery_power_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert status.pv_power_watts == pytest.approx(expected["pv_power_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert status.input_watts == pytest.approx(expected["input_watts"])  # pyright: ignore[reportUnknownMemberType]
    assert status.temp == pytest.approx(expected["temp"])  # pyright: ignore[reportUnknownMemberType]
    assert status.cycles == expected["cycles"]
    assert status.health == pytest.approx(expected["health"])  # pyright: ignore[reportUnknownMemberType]
    assert status.max_charge_soc == expected["max_charge_soc"]
    assert status.min_discharge_soc == expected["min_discharge_soc"]


def test_stream_ultra_sn_is_set() -> None:
    """from_quota_payload stores the SN on the status object."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    sn = "BK11ZK1B2H5S1478"
    status = StreamUltraStatus.from_quota_payload(sn, {})
    assert status.sn == sn


def test_stream_ultra_online_true() -> None:
    """from_quota_payload marks device as online=True."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    status = StreamUltraStatus.from_quota_payload("X", {})
    assert status.online is True


def test_stream_ultra_default_soc_fields() -> None:
    """Empty payload yields safe defaults for SOC limits."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    status = StreamUltraStatus.from_quota_payload("X", {})
    assert status.max_charge_soc == 95
    assert status.min_discharge_soc == 10


def test_stream_ultra_relay_flags() -> None:
    """relay2Onoff / relay3Onoff are parsed as booleans."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"relay2Onoff": True, "relay3Onoff": False}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.relay2_on is True
    assert status.relay3_on is False


def test_stream_ultra_updated_at_is_set() -> None:
    """from_quota_payload sets updated_at to a non-None datetime."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    status = StreamUltraStatus.from_quota_payload("X", {})
    assert status.updated_at is not None


def test_stream_ultra_feed_grid_mode() -> None:
    """feedGridMode is stored as int."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"feedGridMode": 2}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.feed_grid_mode == 2


def test_stream_ultra_battery_power() -> None:
    """powGetBpCms maps to battery_power_watts as float."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"powGetBpCms": -500.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.battery_power_watts == pytest.approx(-500.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_backup_reserve_soc() -> None:
    """backupReverseSoc (API typo: 'Reverse' not 'Reserve') → backup_reserve_soc."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"backupReverseSoc": 13}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.backup_reserve_soc == 13


# ---------------------------------------------------------------------------
# New tests for bmsBattSoc / cmsBattSoc SOC logic (Finding 2)
# ---------------------------------------------------------------------------


def test_stream_ultra_batt_soc_uses_bms_batt_soc_primary() -> None:
    """batt_soc is populated from bmsBattSoc (individual battery SOC) as primary."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"bmsBattSoc": 47.0, "cmsBattSoc": 45.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.batt_soc == pytest.approx(47.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_batt_soc_falls_back_to_cms_when_bms_zero() -> None:
    """batt_soc falls back to cmsBattSoc when bmsBattSoc is 0 (master-only quirk)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"bmsBattSoc": 0.0, "cmsBattSoc": 45.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.batt_soc == pytest.approx(45.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_slave_unit_batt_soc() -> None:
    """Slave STREAM AC Pro: cmsBattSoc=0, bmsBattSoc=47 → batt_soc=47 (not 0)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    # This is the exact scenario seen from live STREAM AC Pro slave unit
    payload = {"bmsBattSoc": 47.0, "cmsBattSoc": 0.0}
    status = StreamUltraStatus.from_quota_payload("BK31SLAVE", payload)
    assert status.batt_soc == pytest.approx(47.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_cascade_soc() -> None:
    """cascadeSysSoc maps to cascade_soc as int."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"cascadeSysSoc": 44}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.cascade_soc == 44


def test_stream_ultra_charge_discharge_state() -> None:
    """chgDsgState maps to charge_discharge_state (1=charging, 2=discharging)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"chgDsgState": 2}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.charge_discharge_state == 2


def test_stream_ultra_input_output_watts() -> None:
    """inputWatts / outputWatts map to input_watts / output_watts."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"inputWatts": 970, "outputWatts": 0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.input_watts == pytest.approx(970.0)  # pyright: ignore[reportUnknownMemberType]
    assert status.output_watts == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_temperature() -> None:
    """temp maps to temp field in °C."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"temp": 35}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.temp == pytest.approx(35.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_battery_voltage_mv_to_v() -> None:
    """vBat (mV) is converted to V on battery_voltage."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"vBat": 20135}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.battery_voltage == pytest.approx(20.135)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_cycles() -> None:
    """cycles maps to cycles field as int."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"cycles": 219}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.cycles == 219


def test_stream_ultra_remaining_cap_wh() -> None:
    """remaining_cap_wh is computed as remainCap_mAh × vBat_mV / 1_000_000.

    UNIT FIX: remainCap is in mAh (not 10mAh units as previously assumed).
    Wh = (mAh × mV) / 1_000_000. Returns 0.0 when vBat is absent.
    Source: tolwi/hassio-ecoflow-cloud research 2026-05-29.
    """
    from ecoflow.models.stream_ultra import StreamUltraStatus

    # With vBat: (46495 mAh × 20135 mV) / 1_000_000 ≈ 936.18 Wh
    payload = {"remainCap": 46495, "vBat": 20135}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.remaining_cap_wh == pytest.approx(936.18, abs=1.0)  # pyright: ignore[reportUnknownMemberType]

    # Without vBat: should return 0.0
    payload_no_vbat = {"remainCap": 46495}
    status2 = StreamUltraStatus.from_quota_payload("X", payload_no_vbat)
    assert status2.remaining_cap_wh == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_full_cap_wh() -> None:
    """full_cap_wh is computed as fullCap_mAh × vBat_mV / 1_000_000.

    UNIT FIX: fullCap is in mAh (not 10mAh units as previously assumed).
    Source: tolwi/hassio-ecoflow-cloud research 2026-05-29.
    """
    from ecoflow.models.stream_ultra import StreamUltraStatus

    # With vBat: (100000 mAh × 20135 mV) / 1_000_000 ≈ 2013.5 Wh
    payload = {"fullCap": 100000, "vBat": 20135}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.full_cap_wh == pytest.approx(2013.5, abs=1.0)  # pyright: ignore[reportUnknownMemberType]

    # Without vBat: should return 0.0
    payload_no_vbat = {"fullCap": 100000}
    status2 = StreamUltraStatus.from_quota_payload("X", payload_no_vbat)
    assert status2.full_cap_wh == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_health() -> None:
    """soh (state of health %) maps to health field."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"soh": 100}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.health == pytest.approx(100.0)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Step 4 new tests: soc_precise, raw mAh capacity fields, Wh via mAh×vBat/1e6
# ---------------------------------------------------------------------------


def test_stream_ultra_soc_precise_from_f32ShowSoc() -> None:
    """f32ShowSoc maps to soc_precise as float (what the EcoFlow app displays)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"f32ShowSoc": 45.540928}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.soc_precise == pytest.approx(45.540928)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_soc_precise_default_zero() -> None:
    """Empty payload yields soc_precise=0.0."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    status = StreamUltraStatus.from_quota_payload("X", {})
    assert status.soc_precise == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_remaining_cap_mah_raw() -> None:
    """remainCap maps to remaining_cap_mah as int (raw mAh)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"remainCap": 46495}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.remaining_cap_mah == 46495


def test_stream_ultra_full_cap_mah_raw() -> None:
    """fullCap maps to full_cap_mah as int (raw mAh)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"fullCap": 100000}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.full_cap_mah == 100000


def test_stream_ultra_design_cap_mah_raw() -> None:
    """designCap maps to design_cap_mah as int (factory capacity in mAh)."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"designCap": 100000}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.design_cap_mah == 100000


def test_stream_ultra_remaining_cap_wh_uses_vbat_formula() -> None:
    """remaining_cap_wh = (remainCap_mAh × vBat_mV) / 1_000_000."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    # 46495 mAh × 20135 mV / 1_000_000 = 936.18 Wh (approximately)
    payload = {"remainCap": 46495, "vBat": 20135}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.remaining_cap_wh == pytest.approx(936.18, abs=1.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_full_cap_wh_uses_vbat_formula() -> None:
    """full_cap_wh = (fullCap_mAh × vBat_mV) / 1_000_000."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    # 100000 mAh × 20135 mV / 1_000_000 = 2013.5 Wh
    payload = {"fullCap": 100000, "vBat": 20135}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.full_cap_wh == pytest.approx(2013.5, abs=1.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_cap_wh_zero_when_no_vbat() -> None:
    """remaining_cap_wh and full_cap_wh are 0.0 when vBat is absent/zero."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"remainCap": 46495, "fullCap": 100000}  # no vBat
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.remaining_cap_wh == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]
    assert status.full_cap_wh == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Step 4 new tests: load source breakdown, Schuko outlets, system grid, time
# ---------------------------------------------------------------------------


def test_stream_ultra_load_from_battery() -> None:
    """powGetSysLoadFromBp maps to load_from_battery_watts."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"powGetSysLoadFromBp": 300.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.load_from_battery_watts == pytest.approx(300.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_load_from_grid() -> None:
    """powGetSysLoadFromGrid maps to load_from_grid_watts."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"powGetSysLoadFromGrid": 450.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.load_from_grid_watts == pytest.approx(450.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_load_from_pv() -> None:
    """powGetSysLoadFromPv maps to load_from_pv_watts."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"powGetSysLoadFromPv": 200.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.load_from_pv_watts == pytest.approx(200.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_schuko_outlets() -> None:
    """powGetSchuko1/2 map to schuko1_watts/schuko2_watts."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"powGetSchuko1": 110.0, "powGetSchuko2": 220.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.schuko1_watts == pytest.approx(110.0)  # pyright: ignore[reportUnknownMemberType]
    assert status.schuko2_watts == pytest.approx(220.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_system_grid_power() -> None:
    """sysGridConnectionPower maps to system_grid_power_watts."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"sysGridConnectionPower": -500.0}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.system_grid_power_watts == pytest.approx(-500.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_remaining_time() -> None:
    """remainTime maps to remaining_time_min as int."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"remainTime": 120}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.remaining_time_min == 120


def test_stream_ultra_charge_time_remaining() -> None:
    """bmsChgRemTime maps to charge_time_remaining_min as int."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"bmsChgRemTime": 45}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.charge_time_remaining_min == 45


def test_stream_ultra_discharge_time_remaining() -> None:
    """bmsDsgRemTime maps to discharge_time_remaining_min as int."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload = {"bmsDsgRemTime": 300}
    status = StreamUltraStatus.from_quota_payload("X", payload)
    assert status.discharge_time_remaining_min == 300


def test_stream_ultra_vector_new_fields() -> None:
    """Vector test: new fields are parsed from the real MQTT payload."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    payload, expected = load_vector("stream_ultra", "payload_status")
    status = StreamUltraStatus.from_quota_payload("BK11ZK1B2H5S1478", payload)

    assert status.soc_precise == pytest.approx(expected["soc_precise"])  # pyright: ignore[reportUnknownMemberType]
    assert status.remaining_cap_mah == expected["remaining_cap_mah"]
    assert status.full_cap_mah == expected["full_cap_mah"]
    wh_approx = pytest.approx(expected["remaining_cap_wh"], abs=5.0)  # pyright: ignore[reportUnknownMemberType]
    assert status.remaining_cap_wh == wh_approx
