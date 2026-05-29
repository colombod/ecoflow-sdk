"""Smart meter device models for EcoFlow grid energy monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class SmartMeterData:
    """Live grid data from an EcoFlow Smart Home Meter (3-phase capable).

    NOTE: Smart Meter returns empty {} from REST /quota/all.
    Data arrives exclusively via MQTT topic /open/{user_id}/{sn}/quota.
    Confirmed from live device BK21Z1BB7H414753 on 2026-05-29.
    """

    sn: str = ""
    product_name: str = ""
    online: bool = False

    # System-level totals
    grid_power_watts: float = 0.0
    """Total grid power. Positive = importing, negative = exporting.

    From powGetSysGrid.
    """
    grid_status: str = ""
    """Grid connection status string (e.g. 'PANEL_GRID_IN'). From gridConnectionSta."""
    power_factor: float = 0.0

    # Per-phase readings (L1/L2/L3 — L2 and L3 are 0.0 on single-phase installs)
    voltage_l1: float = 0.0
    voltage_l2: float = 0.0
    voltage_l3: float = 0.0
    power_l1: float = 0.0
    power_l2: float = 0.0
    power_l3: float = 0.0
    current_l1: float = 0.0
    current_l2: float = 0.0
    current_l3: float = 0.0
    phase_l1_active: bool = False
    phase_l2_active: bool = False
    phase_l3_active: bool = False

    # Energy totals (units are Wh based on field scale)
    total_active_energy_wh: float = 0.0
    today_active_energy_wh: float = 0.0
    total_reactive_energy_varh: float = 0.0

    updated_at: datetime | None = None

    @classmethod
    def from_quota_payload(cls, sn: str, data: dict) -> SmartMeterData:  # type: ignore[type-arg]
        """Parse MQTT quota payload for Smart Home Meter (BK21 devices).

        NOTE: Smart Meter returns empty {} from REST /quota/all.
        Data arrives exclusively via MQTT topic /open/{user_id}/{sn}/quota.
        """
        record = data.get("gridConnectionDataRecord", {})
        return cls(
            sn=sn,
            online=True,
            grid_power_watts=float(data.get("powGetSysGrid", 0)),
            grid_status=str(data.get("gridConnectionSta", "")),
            power_factor=float(data.get("gridConnectionPowerFactor", 0)),
            voltage_l1=float(data.get("gridConnectionVolL1", 0)),
            voltage_l2=float(data.get("gridConnectionVolL2", 0)),
            voltage_l3=float(data.get("gridConnectionVolL3", 0)),
            power_l1=float(data.get("gridConnectionPowerL1", 0)),
            power_l2=float(data.get("gridConnectionPowerL2", 0)),
            power_l3=float(data.get("gridConnectionPowerL3", 0)),
            current_l1=float(data.get("gridConnectionAmpL1", 0)),
            current_l2=float(data.get("gridConnectionAmpL2", 0)),
            current_l3=float(data.get("gridConnectionAmpL3", 0)),
            phase_l1_active=bool(data.get("gridConnectionFlagL1", False)),
            phase_l2_active=bool(data.get("gridConnectionFlagL2", False)),
            phase_l3_active=bool(data.get("gridConnectionFlagL3", False)),
            total_active_energy_wh=float(record.get("totalActiveEnergy", 0)),
            today_active_energy_wh=float(record.get("todayActive", 0)),
            total_reactive_energy_varh=float(record.get("totalReactiveEnergy", 0)),
            updated_at=datetime.now(UTC),
        )

    # Alias for clarity when called from MQTT dispatch path.
    from_mqtt_payload = from_quota_payload
