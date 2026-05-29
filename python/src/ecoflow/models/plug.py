"""Smart Plug device model for EcoFlow Smart Plug series."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# QUIRK: raw 'watts' field is 10× actual wattage.
# Confirmed against Smart Plug firmware v1.x, 2024-11.
# See test test_watts_raw_factor_is_documented and vector
# tests/vectors/smart_plug/payload_power.json (raw=2640 → actual=264.0 W).
# If this constant needs updating, the firmware patched the scaling factor.
_WATTS_RAW_FACTOR: float = 0.1

# MQTT-only factors — used by from_mqtt_payload() for the plug_heartbeat format.
# NOT used by from_quota_payload() — the REST quota/all response has different scaling.
# raw=2300 → 230.0 V  (MQTT format only)
_VOL_RAW_FACTOR: float = 0.1

# raw=54 → 0.54 A  (MQTT format only)
_CURR_RAW_FACTOR: float = 0.01

# raw=456 → 45.6 Wh  (MQTT format only)
_ENERGY_RAW_FACTOR: float = 0.1


@dataclass
class SmartPlugData:
    """Snapshot of EcoFlow Smart Plug state parsed from an MQTT heartbeat."""

    sn: str
    product_name: str
    online: bool
    is_on: bool
    power_watts: float
    """Actual wattage in W. QUIRK: raw 'watts' field is 10× (× _WATTS_RAW_FACTOR)."""
    voltage: float
    current: float
    daily_energy_wh: float
    on_time_seconds: int
    temp: float
    brightness: int = field(default=100)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_mqtt_payload(cls, sn: str, data: dict) -> SmartPlugData:  # type: ignore[type-arg]
        """Build a SmartPlugData snapshot from a raw MQTT payload dict."""
        hb: dict = data.get("plug_heartbeat", data)  # type: ignore[type-arg]

        # is_on comes from plugState (int) or switch (int) fallback
        raw_state = hb.get("plugState", hb.get("switch", 0))
        is_on = bool(raw_state)

        return cls(
            sn=sn,
            product_name="",
            online=True,
            is_on=is_on,
            power_watts=float(hb.get("watts", 0)) * _WATTS_RAW_FACTOR,
            voltage=float(hb.get("vol", 0)) * _VOL_RAW_FACTOR,
            current=float(hb.get("curr", 0)) * _CURR_RAW_FACTOR,
            daily_energy_wh=float(hb.get("watth5", 0)) * _ENERGY_RAW_FACTOR,
            on_time_seconds=int(hb.get("onTime", 0)),
            temp=float(hb.get("temp", 0)) / 10.0,
            brightness=int(hb.get("brightness", 100)),
            updated_at=datetime.now(UTC),
        )

    @classmethod
    def from_quota_payload(cls, sn: str, data: dict) -> SmartPlugData:  # type: ignore[type-arg]
        """Parse the REST /quota/all response (flat 2_1.* keys).

        QUIRK: REST quota/all response uses flat '2_1.*' key format.
        Confirmed from live device BK11/HW52 series. 2026-05.
        QUIRK: 'volt' is already in Volts (no factor). Original MQTT assumption of
        0.1 factor does NOT apply here.
        QUIRK: 'temp' is already in °C (no /10). MQTT uses /10, REST does not.
        QUIRK: 'watts' still requires ×0.1 factor (confirmed: 2640 raw → 264W actual).
        QUIRK: 'switchSta' is a boolean, not int.
        """
        raw_brightness = data.get("2_1.brightness", 0)
        return cls(
            sn=sn,
            product_name="",
            online=True,
            is_on=bool(data.get("2_1.switchSta", False)),
            power_watts=data.get("2_1.watts", 0) * _WATTS_RAW_FACTOR,
            voltage=float(data.get("2_1.volt", 0)),  # already Volts — no factor
            current=data.get("2_1.current", 0) / 1000.0,  # mA → A
            daily_energy_wh=0.0,  # not available in quota/all
            on_time_seconds=data.get("2_1.runTime", 0),
            temp=float(data.get("2_1.temp", 0)),  # already °C — no /10
            brightness=round(raw_brightness / 1023 * 100) if raw_brightness > 0 else 0,
            updated_at=datetime.now(UTC),
        )
