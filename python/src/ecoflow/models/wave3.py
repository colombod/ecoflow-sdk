"""Wave 3 portable air conditioner models for EcoFlow Wave series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any


class Wave3Mode(IntEnum):
    """Operating mode for the Wave 3 portable AC."""

    COOL = 0
    HEAT = 1
    FAN = 2
    DRY = 3
    AUTO = 4


@dataclass
class Wave3Status:
    """Snapshot of EcoFlow Wave 3 portable AC state parsed from an MQTT payload."""

    sn: str
    product_name: str
    online: bool
    is_on: bool
    mode: Wave3Mode = Wave3Mode.COOL
    target_temp: float = 26.0
    """Set temperature in °C (raw field is ×10)"""
    indoor_temp: float = 0.0
    outdoor_temp: float = 0.0
    fan_speed: int = 0
    """0=auto, 1=low, 2=medium, 3=high"""
    power_watts: float = 0.0
    battery_soc: float = 0.0
    battery_temp: float = 0.0
    battery_voltage: float = 0.0
    charge_mode: int = 0
    humidity_pct: float = 0.0
    updated_at: datetime | None = None

    @classmethod
    def from_mqtt_payload(cls, sn: str, data: dict[str, Any]) -> Wave3Status:
        """Build a Wave3Status snapshot from a raw MQTT payload dict."""
        pd: dict[str, Any] = data.get("pd", data)
        bms: dict[str, Any] = data.get("bms", {})

        return cls(
            sn=sn,
            product_name="",
            online=True,
            is_on=bool(pd.get("powerMode", 0)),
            mode=Wave3Mode(pd.get("waveMode", 0)),
            target_temp=float(pd.get("setTemp", 260)) / 10.0,
            indoor_temp=float(pd.get("tempInVol", 0)) / 10.0,
            outdoor_temp=float(pd.get("tempOutVol", 0)) / 10.0,
            fan_speed=int(pd.get("fanValue", 0)),
            power_watts=float(pd.get("wattsPower", 0)),
            battery_soc=float(bms.get("soc", 0)),
            battery_temp=float(bms.get("temp", 0)) / 10.0,
            battery_voltage=float(bms.get("vol", 0)) / 1000.0,
            charge_mode=int(pd.get("chargeMode", 0)),
            humidity_pct=float(pd.get("envHumiVol", 0)) / 10.0,
            updated_at=datetime.now(UTC),
        )
