"""Wave 3 portable air conditioner models for EcoFlow Wave series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any


class Wave3Mode(IntEnum):
    """Operating mode for the Wave 3 portable AC."""

    NONE = 0  # off / standby
    COOLING = 1
    HEATING = 2
    VENTING = 3  # fan-only
    DEHUMIDIFYING = 4
    THERMOSTATIC = 5  # thermostat range mode

    def __str__(self) -> str:
        """Return ClassName.MEMBER_NAME format (consistent across Python versions)."""
        return f"{type(self).__name__}.{self.name}"


# Raw airflow speed → fan level mapping
_FAN_SPEED_MAP: dict[int, int] = {20: 1, 40: 2, 60: 3, 80: 4, 100: 5}


@dataclass
class Wave3Status:
    """Snapshot of EcoFlow Wave 3 portable AC state from a Protobuf MQTT payload."""

    sn: str = ""
    product_name: str = ""
    online: bool = False
    # QUIRK: derived from (dev_sleep_state != 1) AND (wave_operating_mode != 0)
    is_on: bool = False
    mode: Wave3Mode = Wave3Mode.NONE
    ambient_temp: float = 0.0  # temp_ambient
    supply_air_temp: float = 0.0  # temp_indoor_supply_air
    target_temp: float = 22.0  # current_temp_set (from wave_mode_info)
    target_temp_high: float = 24.0  # current_temp_thermostatic_upper_limit
    target_temp_low: float = 20.0  # current_temp_thermostatic_lower_limit
    condenser_temp: float = 0.0  # temp_condenser
    evaporator_temp: float = 0.0  # temp_evaporator
    outdoor_temp: float = 0.0  # temp_outdoor_ambient
    compressor_discharge_temp: float = 0.0  # temp_compressor_discharge
    airflow_speed: int = 20  # current_airflow_speed (raw: 20/40/60/80/100)
    # NOTE: fan_level 1–5 is a read-only status field (from raw airflow_speed).
    # It is NOT the same scale as Wave3Device.set_fan_speed() (0–3: auto/low/mid/high).
    # Do not pass fan_level directly to set_fan_speed().
    fan_level: int = 1  # mapped: {20:1, 40:2, 60:3, 80:4, 100:5}
    submode: int = 0  # current_submode: 0=none, 2=boost, 3=sleep, 4=eco
    ambient_humidity: float = 0.0  # humi_ambient
    target_humidity: float = 50.0  # current_humi_set
    battery_soc: float = 0.0  # bms_batt_soc
    system_soc: float = 0.0  # cms_batt_soc
    bms_discharge_time_min: int = 0  # bms_dsg_rem_time
    bms_charge_time_min: int = 0  # bms_chg_rem_time
    discharge_time_min: int = 0  # cms_dsg_rem_time (system)
    charge_time_min: int = 0  # cms_chg_rem_time (system)
    input_power_watts: float = 0.0  # pow_in_sum_w
    output_power_watts: float = 0.0  # pow_out_sum_w
    ac_power_watts: float = 0.0  # pow_get_ac
    """AC-side power (W). Recorded live 2026-09-28: equals self-consumption
    (41.6 W) while running from the AC outlet — the only AC power figure this
    firmware sends."""
    ac_input_power_watts: float = 0.0  # pow_get_ac_in
    """Not sent by current firmware (observed 0 while charging at ~700 W from
    AC, 2026-09-28). Use ``ac_power_watts`` / ``ac_plugged_in``."""
    battery_power_watts: float = 0.0  # pow_get_bms
    """Battery power (W): POSITIVE = charging, NEGATIVE = discharging (verified
    live: +700 W recharging from AC, -18 W with the AC outlet switched off)."""
    ac_plugged_in: bool = False  # plug_in_info_ac_in_flag
    ac_input_voltage: float = 0.0  # plug_in_info_ac_in_vol (V) — runtime msg 254/22
    battery_voltage: float = 0.0  # bms_batt_vol mV -> V — runtime msg 254/22
    battery_current_amps: float = 0.0  # bms_batt_amp mA -> A (negative = discharge)
    pv_power_watts: float = 0.0  # pow_get_pv
    self_consume_watts: float = 0.0  # pow_get_self_consume
    water_level: int = 0  # condensate_water_level (0-100%)
    updated_at: datetime | None = None

    @classmethod
    def from_mqtt_payload(cls, payload: dict[str, Any]) -> Wave3Status:
        """Build a Wave3Status from a decoded Protobuf payload dict.

        Args:
            payload: Flat dict keyed by snake_case Protobuf field names.
                     Temperatures are native float °C (not ×10 encoded).
        """
        dev_sleep_state = int(payload.get("dev_sleep_state", 1))
        wave_operating_mode = int(payload.get("wave_operating_mode", 0))
        is_on = (dev_sleep_state != 1) and (wave_operating_mode != 0)

        mode_val = wave_operating_mode
        mode = Wave3Mode(mode_val) if mode_val in range(6) else Wave3Mode.NONE

        raw_speed = int(payload.get("current_airflow_speed", 20))
        fan_level = _FAN_SPEED_MAP.get(raw_speed, 1)

        return cls(
            sn=str(payload.get("sn", "")),
            online=True,
            is_on=is_on,
            mode=mode,
            ambient_temp=float(payload.get("temp_ambient", 0.0)),
            supply_air_temp=float(payload.get("temp_indoor_supply_air", 0.0)),
            target_temp=float(payload.get("current_temp_set", 22.0)),
            target_temp_high=float(
                payload.get("current_temp_thermostatic_upper_limit", 24.0)
            ),
            target_temp_low=float(
                payload.get("current_temp_thermostatic_lower_limit", 20.0)
            ),
            condenser_temp=float(payload.get("temp_condenser", 0.0)),
            evaporator_temp=float(payload.get("temp_evaporator", 0.0)),
            outdoor_temp=float(payload.get("temp_outdoor_ambient", 0.0)),
            compressor_discharge_temp=float(
                payload.get("temp_compressor_discharge", 0.0)
            ),
            airflow_speed=raw_speed,
            fan_level=fan_level,
            submode=int(payload.get("current_submode", 0)),
            ambient_humidity=float(payload.get("humi_ambient", 0.0)),
            target_humidity=float(payload.get("current_humi_set", 50.0)),
            battery_soc=float(payload.get("bms_batt_soc", 0.0)),
            system_soc=float(payload.get("cms_batt_soc", 0.0)),
            bms_discharge_time_min=int(payload.get("bms_dsg_rem_time", 0)),
            bms_charge_time_min=int(payload.get("bms_chg_rem_time", 0)),
            discharge_time_min=int(payload.get("cms_dsg_rem_time", 0)),
            charge_time_min=int(payload.get("cms_chg_rem_time", 0)),
            input_power_watts=float(payload.get("pow_in_sum_w", 0.0)),
            output_power_watts=float(payload.get("pow_out_sum_w", 0.0)),
            ac_power_watts=float(payload.get("pow_get_ac", 0.0)),
            ac_input_power_watts=float(payload.get("pow_get_ac_in", 0.0)),
            battery_power_watts=float(payload.get("pow_get_bms", 0.0)),
            ac_plugged_in=bool(payload.get("plug_in_info_ac_in_flag", 0)),
            ac_input_voltage=float(payload.get("plug_in_info_ac_in_vol", 0.0)),
            battery_voltage=float(payload.get("bms_batt_vol", 0.0)) / 1000.0,
            battery_current_amps=float(payload.get("bms_batt_amp", 0.0)) / 1000.0,
            pv_power_watts=float(payload.get("pow_get_pv", 0.0)),
            self_consume_watts=float(payload.get("pow_get_self_consume", 0.0)),
            water_level=int(payload.get("condensate_water_level", 0)),
            updated_at=datetime.now(UTC),
        )
