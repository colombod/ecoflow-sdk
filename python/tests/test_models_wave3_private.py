"""Private tests for Wave3Mode enum and Wave3Status Protobuf field mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from ecoflow.models.wave3 import Wave3Mode, Wave3Status

# ---------------------------------------------------------------------------
# Real device payload fixtures (from live E2E against AC71 series, 2026-05-31)
# ---------------------------------------------------------------------------

# Real Wave3 active state payload (from live E2E against AC71 series, 2026-05-31)
ACTIVE_PAYLOAD: dict[str, Any] = {
    "wave_operating_mode": 1,  # COOLING
    "dev_sleep_state": 0,  # awake
    "bms_batt_soc": 84.80,
    "temp_ambient": 20.78,
    "temp_indoor_supply_air": 18.74,
    "current_temp_set": 25.0,  # extracted by decoder from wave_mode_info
    "current_airflow_speed": 60,
    "current_submode": 0,
    "pow_get_ac": 34.0,
    "pow_in_sum_w": 34.0,
    "condensate_water_level": 0.0,
}

# Standby state (partial update — only a few fields reported)
STANDBY_PAYLOAD: dict[str, Any] = {
    "wave_operating_mode": 0,  # NONE
    "dev_sleep_state": 1,  # sleeping
    "pow_get_ac": 1.54,
}


class TestWave3ModeEnum:
    """Wave3Mode enum has correct integer values per Protobuf schema."""

    def test_none_is_0(self) -> None:
        assert Wave3Mode.NONE.value == 0

    def test_cooling_is_1(self) -> None:
        assert Wave3Mode.COOLING.value == 1

    def test_heating_is_2(self) -> None:
        assert Wave3Mode.HEATING.value == 2

    def test_venting_is_3(self) -> None:
        assert Wave3Mode.VENTING.value == 3

    def test_dehumidifying_is_4(self) -> None:
        assert Wave3Mode.DEHUMIDIFYING.value == 4

    def test_thermostatic_is_5(self) -> None:
        assert Wave3Mode.THERMOSTATIC.value == 5

    def test_str_format_includes_class_name(self) -> None:
        """str(Wave3Mode.X) returns 'Wave3Mode.X' across Python versions."""
        assert str(Wave3Mode.COOLING) == "Wave3Mode.COOLING"
        assert str(Wave3Mode.NONE) == "Wave3Mode.NONE"


class TestIsOnDerivation:
    """is_on is derived from dev_sleep_state AND wave_operating_mode."""

    def test_is_on_true_when_not_sleeping_and_mode_nonzero(self) -> None:
        status = Wave3Status.from_mqtt_payload(
            {"dev_sleep_state": 0, "wave_operating_mode": 1}
        )
        assert status.is_on is True

    def test_is_on_false_when_sleep_state_is_1(self) -> None:
        """is_on=False when dev_sleep_state=1, even if mode is non-zero."""
        status = Wave3Status.from_mqtt_payload(
            {"dev_sleep_state": 1, "wave_operating_mode": 1}
        )
        assert status.is_on is False

    def test_is_on_false_when_wave_operating_mode_is_0(self) -> None:
        """is_on=False when wave_operating_mode=0, even if sleep_state=0."""
        status = Wave3Status.from_mqtt_payload(
            {"dev_sleep_state": 0, "wave_operating_mode": 0}
        )
        assert status.is_on is False

    def test_is_on_false_when_both_conditions_not_met(self) -> None:
        status = Wave3Status.from_mqtt_payload(
            {"dev_sleep_state": 1, "wave_operating_mode": 0}
        )
        assert status.is_on is False


class TestFanLevelMapping:
    """fan_level maps airflow_speed raw values 20/40/60/80/100 to levels 1–5."""

    @pytest.mark.parametrize(
        ("raw_speed", "expected_level"),
        [
            (20, 1),
            (40, 2),
            (60, 3),
            (80, 4),
            (100, 5),
        ],
    )
    def test_fan_level_mapping(self, raw_speed: int, expected_level: int) -> None:
        status = Wave3Status.from_mqtt_payload({"current_airflow_speed": raw_speed})
        assert status.fan_level == expected_level

    def test_fan_level_unknown_speed_defaults_to_1(self) -> None:
        """Unknown airflow speed (e.g., 50) defaults to fan_level=1."""
        status = Wave3Status.from_mqtt_payload({"current_airflow_speed": 50})
        assert status.fan_level == 1


class TestTemperatureFields:
    """Temperatures are native float °C — NOT ×10 encoded."""

    def test_target_temp_default_is_22(self) -> None:
        status = Wave3Status()
        assert status.target_temp == 22.0

    def test_target_temp_not_26(self) -> None:
        """Regression guard: old default was 26.0 — must now be 22.0."""
        status = Wave3Status()
        assert status.target_temp != 26.0

    def test_target_temp_from_payload_is_native_float(self) -> None:
        """24.0 in proto payload → 24.0 in status (no ×10 conversion)."""
        status = Wave3Status.from_mqtt_payload({"current_temp_set": 24.0})
        assert status.target_temp == pytest.approx(24.0)  # pyright: ignore[reportUnknownMemberType]

    def test_target_temp_not_divided_by_10(self) -> None:
        """Regression guard: proto sends 24.0 directly, not 240 requiring ÷10."""
        status = Wave3Status.from_mqtt_payload({"current_temp_set": 240.0})
        assert status.target_temp == pytest.approx(240.0)  # pyright: ignore[reportUnknownMemberType]


class TestFromMqttPayload:
    """from_mqtt_payload() builds Wave3Status from proto field names."""

    def test_empty_payload_returns_online_true(self) -> None:
        status = Wave3Status.from_mqtt_payload({})
        assert status.online is True

    def test_empty_payload_returns_default_target_temp(self) -> None:
        status = Wave3Status.from_mqtt_payload({})
        assert status.target_temp == pytest.approx(22.0)  # pyright: ignore[reportUnknownMemberType]

    def test_sets_sn_from_payload(self) -> None:
        status = Wave3Status.from_mqtt_payload({"sn": "AC71XTEST"})
        assert status.sn == "AC71XTEST"

    def test_sets_online_true_always(self) -> None:
        status = Wave3Status.from_mqtt_payload({})
        assert status.online is True

    def test_sets_updated_at(self) -> None:
        before = datetime.now(UTC)
        status = Wave3Status.from_mqtt_payload({})
        after = datetime.now(UTC)
        assert status.updated_at is not None
        assert before <= status.updated_at <= after

    def test_full_cooling_payload(self) -> None:
        """Full cooling payload maps all major proto fields correctly."""
        payload = {
            "sn": "AC71COOLING",
            "dev_sleep_state": 0,
            "wave_operating_mode": 1,
            "current_temp_set": 22.5,
            "current_temp_thermostatic_upper_limit": 25.0,
            "current_temp_thermostatic_lower_limit": 19.0,
            "temp_ambient": 28.3,
            "temp_indoor_supply_air": 14.0,
            "temp_condenser": 45.0,
            "temp_evaporator": 10.0,
            "temp_outdoor_ambient": 30.0,
            "temp_compressor_discharge": 65.0,
            "current_airflow_speed": 60,
            "current_submode": 2,
            "humi_ambient": 65.0,
            "current_humi_set": 50.0,
            "bms_batt_soc": 80.0,
            "cms_batt_soc": 75.0,
            "bms_dsg_rem_time": 120,
            "bms_chg_rem_time": 60,
            "cms_dsg_rem_time": 100,
            "cms_chg_rem_time": 90,
            "pow_in_sum_w": 1200.0,
            "pow_out_sum_w": 1100.0,
            "pow_get_ac": 1000.0,
            "pow_get_ac_in": 500.0,
            "pow_get_bms": 300.0,
            "pow_get_pv": 400.0,
            "pow_get_self_consume": 50.0,
            "condensate_water_level": 30,
        }
        status = Wave3Status.from_mqtt_payload(payload)

        assert status.sn == "AC71COOLING"
        assert status.online is True
        assert status.is_on is True
        assert status.mode == Wave3Mode.COOLING
        assert status.target_temp == pytest.approx(22.5)  # pyright: ignore[reportUnknownMemberType]
        assert status.target_temp_high == pytest.approx(25.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.target_temp_low == pytest.approx(19.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.ambient_temp == pytest.approx(28.3)  # pyright: ignore[reportUnknownMemberType]
        assert status.supply_air_temp == pytest.approx(14.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.condenser_temp == pytest.approx(45.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.evaporator_temp == pytest.approx(10.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.outdoor_temp == pytest.approx(30.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.compressor_discharge_temp == pytest.approx(65.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.airflow_speed == 60
        assert status.fan_level == 3
        assert status.submode == 2
        assert status.ambient_humidity == pytest.approx(65.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.target_humidity == pytest.approx(50.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.battery_soc == pytest.approx(80.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.system_soc == pytest.approx(75.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.bms_discharge_time_min == 120
        assert status.bms_charge_time_min == 60
        assert status.discharge_time_min == 100
        assert status.charge_time_min == 90
        assert status.input_power_watts == pytest.approx(1200.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.output_power_watts == pytest.approx(1100.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.ac_power_watts == pytest.approx(1000.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.ac_input_power_watts == pytest.approx(500.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.battery_power_watts == pytest.approx(300.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.pv_power_watts == pytest.approx(400.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.self_consume_watts == pytest.approx(50.0)  # pyright: ignore[reportUnknownMemberType]
        assert status.water_level == 30
        assert status.updated_at is not None


class TestRealDevicePayloads:
    """Tests using real E2E device observations (2026-05-31, AC71 series).

    ACTIVE_PAYLOAD: Wave 3 actively cooling — 396-byte heartbeat, cmd_id=21.
    STANDBY_PAYLOAD: Wave 3 idle — 48-byte partial update with only power fields.
    """

    def test_active_payload_is_on(self) -> None:
        """Active: dev_sleep_state=0 + wave_operating_mode=1 → is_on=True."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.is_on is True

    def test_active_payload_mode_is_cooling(self) -> None:
        """wave_operating_mode=1 → Wave3Mode.COOLING."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.mode == Wave3Mode.COOLING

    def test_active_payload_battery_soc(self) -> None:
        """bms_batt_soc=84.80 from live device."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.battery_soc == pytest.approx(84.80, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_active_payload_ambient_temp(self) -> None:
        """temp_ambient=20.78 °C from live device."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.ambient_temp == pytest.approx(20.78, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_active_payload_target_temp(self) -> None:
        """current_temp_set=25.0 °C (extracted from wave_mode_info by decoder)."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.target_temp == pytest.approx(25.0, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_active_payload_fan_level(self) -> None:
        """current_airflow_speed=60 (raw) → fan_level=3."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.fan_level == 3

    def test_active_payload_ac_power_watts(self) -> None:
        """pow_get_ac=34.0 W from live device cooling state."""
        status = Wave3Status.from_mqtt_payload(ACTIVE_PAYLOAD)
        assert status.ac_power_watts == pytest.approx(34.0, abs=0.1)  # pyright: ignore[reportUnknownMemberType]

    def test_standby_payload_is_off(self) -> None:
        """Standby: dev_sleep_state=1 → is_on=False."""
        status = Wave3Status.from_mqtt_payload(STANDBY_PAYLOAD)
        assert status.is_on is False

    def test_standby_payload_mode_is_none(self) -> None:
        """Standby: wave_operating_mode=0 → Wave3Mode.NONE."""
        status = Wave3Status.from_mqtt_payload(STANDBY_PAYLOAD)
        assert status.mode == Wave3Mode.NONE

    def test_standby_payload_ac_power_standby_draw(self) -> None:
        """Standby draw: ~1.54 W AC power even when not cooling."""
        status = Wave3Status.from_mqtt_payload(STANDBY_PAYLOAD)
        assert status.ac_power_watts == pytest.approx(1.54, abs=0.1)  # pyright: ignore[reportUnknownMemberType]


# Recorded live 2026-09-28 (Wave 3 on a STREAM Ultra outlet, battery 90 %).
def test_wave3_reads_ac_plug_and_runtime_electricals() -> None:
    from ecoflow.models.wave3 import Wave3Status

    status = Wave3Status.from_mqtt_payload(
        {
            "pow_get_ac": 41.55,
            "plug_in_info_ac_in_flag": 1,
            "plug_in_info_ac_in_vol": 247.0,
            "bms_batt_vol": 53470.0,
            "bms_batt_amp": -79.0,
        }
    )
    assert status.ac_plugged_in is True
    assert status.ac_power_watts == pytest.approx(41.55)  # pyright: ignore[reportUnknownMemberType]
    assert status.ac_input_voltage == pytest.approx(247.0)  # pyright: ignore[reportUnknownMemberType]
    assert status.battery_voltage == pytest.approx(53.47)  # pyright: ignore[reportUnknownMemberType]
    assert status.battery_current_amps == pytest.approx(-0.079)  # pyright: ignore[reportUnknownMemberType]
