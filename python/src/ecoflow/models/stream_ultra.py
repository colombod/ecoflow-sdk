"""STREAM Ultra and STREAM AC Pro data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


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
    cascade_soc: int = 0
    """System-level SOC across all cascaded units. From cascadeSysSoc."""

    # Power flows
    grid_power_watts: float = 0.0
    """Grid power in Watts. Positive = importing, negative = exporting."""
    load_power_watts: float = 0.0
    """Home load power in Watts."""
    pv_power_watts: float = 0.0
    """Solar PV input power in Watts."""
    battery_power_watts: float = 0.0
    """Battery charge/discharge power in Watts."""

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
    remaining_cap_wh: float = 0.0
    """Remaining capacity in Wh (converted from remainCap 10mAh units)."""
    full_cap_wh: float = 0.0
    """Full capacity in Wh (converted from fullCap 10mAh units)."""
    health: float = 0.0
    """State of health %. From soh."""

    updated_at: datetime | None = None

    @classmethod
    def from_quota_payload(cls, sn: str, data: dict) -> StreamUltraStatus:  # type: ignore[type-arg]
        """Parse the REST /quota/all or MQTT quota payload for STREAM Ultra / AC Pro.

        SOC: bmsBattSoc is per-unit real SOC; cmsBattSoc is CMS aggregate
        (returns 0 on slave units in cascaded systems).
        QUIRK: cmsBattSoc = 0.0 on STREAM AC Pro slave units in cascaded systems.
        Always prefer bmsBattSoc (real individual battery SOC) over cmsBattSoc.
        See: Perplexity research 2026-05-29 — master/slave CMS aggregation.
        """
        bms_soc = float(data.get("bmsBattSoc", 0))
        cms_soc = float(data.get("cmsBattSoc", 0))
        batt_soc = bms_soc if bms_soc > 0 else cms_soc

        return cls(
            sn=sn,
            online=True,
            batt_soc=batt_soc,
            cascade_soc=int(data.get("cascadeSysSoc", 0)),
            grid_power_watts=float(data.get("powGetSysGrid", 0)),
            load_power_watts=float(data.get("powGetSysLoad", 0)),
            pv_power_watts=float(data.get("powGetPvSum", 0)),
            battery_power_watts=float(data.get("powGetBpCms", 0)),
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
            remaining_cap_wh=data.get("remainCap", 0) * 0.01,  # 10mAh units → Wh
            full_cap_wh=data.get("fullCap", 0) * 0.01,  # 10mAh units → Wh
            health=float(data.get("soh", 0)),
            updated_at=datetime.now(tz=UTC),
        )
