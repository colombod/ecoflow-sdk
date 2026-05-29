"""STREAM Ultra and STREAM AC Pro data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class StreamUltraStatus:
    """Status snapshot for EcoFlow STREAM Ultra and STREAM AC Pro home energy systems.

    Both device types share the same quota/all payload format.

    SOC NOTE: bmsBattSoc is the per-unit real battery SOC (present on all units
    including STREAM AC Pro slaves in cascaded systems). cmsBattSoc is the CMS
    aggregate which is 0.0 on slave units. from_quota_payload() always prefers
    bmsBattSoc as primary.
    See: Perplexity research 2026-05-29 — master/slave CMS aggregation.
    """

    sn: str = ""
    product_name: str = ""
    online: bool = False

    # Battery state of charge
    batt_soc: float = 0.0
    """Battery SOC 0–100 %. From bmsBattSoc (primary) with cmsBattSoc as fallback."""
    soc_precise: float = 0.0
    """Precise floating-point battery SOC (0–100 %). From f32ShowSoc.
    This is what the EcoFlow app displays. batt_soc is the integer version."""
    cascade_soc: int = 0
    """System-level SOC across all cascaded units. From cascadeSysSoc."""

    # Power flows
    grid_power_watts: float = 0.0
    """Grid power (W) from powGetSysGrid.
    POSITIVE = importing from grid. NEGATIVE = exporting to grid.
    NOTE: The related field gridConnectionPower (→ grid_connection_power) has OPPOSITE
    sign convention: negative = importing, positive = exporting.
    Source: tolwi/hassio-ecoflow-cloud research 2026-05-29."""
    load_power_watts: float = 0.0
    """Home load power in Watts."""
    pv_power_watts: float = 0.0
    """Solar PV input power in Watts."""
    battery_power_watts: float = 0.0
    """Battery charge/discharge power in Watts."""

    # Load source breakdown
    load_from_battery_watts: float = 0.0
    """Load power sourced from battery (W). From powGetSysLoadFromBp."""
    load_from_grid_watts: float = 0.0
    """Load power sourced from grid (W). From powGetSysLoadFromGrid."""
    load_from_pv_watts: float = 0.0
    """Load power sourced from PV (W). From powGetSysLoadFromPv."""

    # Schuko outlets (German-standard AC outlets on STREAM Ultra)
    schuko1_watts: float = 0.0
    """Schuko outlet 1 power (W). From powGetSchuko1."""
    schuko2_watts: float = 0.0
    """Schuko outlet 2 power (W). From powGetSchuko2."""

    # System-level grid (multi-device aggregated across all linked STREAM units)
    system_grid_power_watts: float = 0.0
    """System grid power (W) aggregated across all linked STREAM units.
    From sysGridConnectionPower."""

    # Settings
    max_charge_soc: int = 95
    """Maximum charge SOC limit 0–100 %."""
    min_discharge_soc: int = 10
    """Minimum discharge SOC limit 0–100 %."""
    feed_grid_mode: int = 0
    """Grid feed mode (0=off, 1=on, 2=auto)."""
    grid_connection_power: float = 0.0
    relay2_on: bool = False
    relay3_on: bool = False
    backup_reserve_soc: int = 0

    # Battery detail fields (from MQTT quota payload)
    charge_discharge_state: int = 0
    """Charge/discharge state (1=charging, 2=discharging). From chgDsgState."""
    input_watts: float = 0.0
    """Power going into battery in Watts. From inputWatts."""
    output_watts: float = 0.0
    """Power coming from battery to load in Watts. From outputWatts."""
    temp: float = 0.0
    """Battery temperature in °C. From temp."""
    battery_voltage: float = 0.0
    """Battery voltage in V (converted from vBat mV)."""
    cycles: int = 0
    """Charge/discharge cycle count. From cycles."""

    # Capacity — raw mAh fields
    remaining_cap_mah: int = 0
    """Remaining capacity in mAh (raw). From remainCap."""
    full_cap_mah: int = 0
    """Full capacity in mAh (raw). From fullCap."""
    design_cap_mah: int = 0
    """Design (factory) capacity in mAh (raw). From designCap."""

    # Capacity — computed Wh fields
    remaining_cap_wh: float = 0.0
    """Remaining capacity in Wh. Computed as (remainCap_mAh × vBat_mV) / 1_000_000.
    QUIRK: remainCap/fullCap are in mAh (not 10mAh as earlier assumed).
    Requires vBat > 0; returns 0.0 otherwise. Source: tolwi research 2026-05-29."""
    full_cap_wh: float = 0.0
    """Full capacity in Wh. Computed as (fullCap_mAh × vBat_mV) / 1_000_000.
    See remaining_cap_wh for conversion notes."""

    health: float = 0.0
    """State of health %. From soh."""

    # Remaining time
    remaining_time_min: int = 0
    """Remaining time in minutes (contextual: charge or discharge). From remainTime."""
    charge_time_remaining_min: int = 0
    """Charge time remaining in minutes. From bmsChgRemTime."""
    discharge_time_remaining_min: int = 0
    """Discharge time remaining in minutes. From bmsDsgRemTime."""

    updated_at: datetime | None = None

    @classmethod
    def from_quota_payload(cls, sn: str, data: dict[str, Any]) -> StreamUltraStatus:
        """Parse the REST /quota/all or MQTT quota payload for STREAM Ultra / AC Pro.

        SOC: bmsBattSoc is per-unit real SOC; cmsBattSoc is CMS aggregate
        (returns 0 on slave units in cascaded systems).
        QUIRK: cmsBattSoc = 0.0 on STREAM AC Pro slave units in cascaded systems.
        Always prefer bmsBattSoc (real individual battery SOC) over cmsBattSoc.
        See: Perplexity research 2026-05-29 — master/slave CMS aggregation.

        CAPACITY QUIRK: remainCap/fullCap/designCap are in mAh. vBat is in mV.
        Wh = (mAh × mV) / 1_000_000. Requires vBat > 0.
        Source: tolwi/hassio-ecoflow-cloud research 2026-05-29.
        """
        bms_soc = float(data.get("bmsBattSoc", 0))
        cms_soc = float(data.get("cmsBattSoc", 0))
        batt_soc = bms_soc if bms_soc > 0 else cms_soc

        remain_mah = int(data.get("remainCap", 0))
        full_mah = int(data.get("fullCap", 0))
        vbat_mv = int(data.get("vBat", 0))

        remaining_cap_wh = (remain_mah * vbat_mv) / 1_000_000 if vbat_mv > 0 else 0.0
        full_cap_wh = (full_mah * vbat_mv) / 1_000_000 if vbat_mv > 0 else 0.0

        return cls(
            sn=sn,
            online=True,
            batt_soc=batt_soc,
            soc_precise=float(data.get("f32ShowSoc", 0.0)),
            cascade_soc=int(data.get("cascadeSysSoc", 0)),
            grid_power_watts=float(data.get("powGetSysGrid", 0)),
            load_power_watts=float(data.get("powGetSysLoad", 0)),
            pv_power_watts=float(data.get("powGetPvSum", 0)),
            battery_power_watts=float(data.get("powGetBpCms", 0)),
            load_from_battery_watts=float(data.get("powGetSysLoadFromBp", 0)),
            load_from_grid_watts=float(data.get("powGetSysLoadFromGrid", 0)),
            load_from_pv_watts=float(data.get("powGetSysLoadFromPv", 0)),
            schuko1_watts=float(data.get("powGetSchuko1", 0)),
            schuko2_watts=float(data.get("powGetSchuko2", 0)),
            system_grid_power_watts=float(data.get("sysGridConnectionPower", 0)),
            max_charge_soc=int(data.get("cmsMaxChgSoc", 95)),
            min_discharge_soc=int(data.get("cmsMinDsgSoc", 10)),
            feed_grid_mode=int(data.get("feedGridMode", 0)),
            grid_connection_power=float(data.get("gridConnectionPower", 0)),
            relay2_on=bool(data.get("relay2Onoff", False)),
            relay3_on=bool(data.get("relay3Onoff", False)),
            backup_reserve_soc=int(data.get("backupReverseSoc", 0)),
            charge_discharge_state=int(data.get("chgDsgState", 0)),
            input_watts=float(data.get("inputWatts", 0)),
            output_watts=float(data.get("outputWatts", 0)),
            temp=float(data.get("temp", 0)),
            battery_voltage=data.get("vBat", 0) / 1000.0,  # mV → V
            cycles=int(data.get("cycles", 0)),
            remaining_cap_mah=remain_mah,
            full_cap_mah=full_mah,
            design_cap_mah=int(data.get("designCap", 0)),
            remaining_cap_wh=remaining_cap_wh,
            full_cap_wh=full_cap_wh,
            health=float(data.get("soh", 0)),
            remaining_time_min=int(data.get("remainTime", 0)),
            charge_time_remaining_min=int(data.get("bmsChgRemTime", 0)),
            discharge_time_remaining_min=int(data.get("bmsDsgRemTime", 0)),
            updated_at=datetime.now(tz=UTC),
        )
