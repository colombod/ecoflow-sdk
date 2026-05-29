"""Battery device models for EcoFlow PowerStation series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class BmsModule:
    """BMS (Battery Management System) module status."""

    module_sn: str | None
    soc: float
    voltage: float  # V (converted from mV via /1000)
    current: float  # A (converted from mA via /1000)
    temp: float  # °C (raw/10)
    cycles: int
    design_cap: int
    full_cap: int
    remain_cap: int
    health: int
    min_cell_temp: float  # °C (raw/10)
    max_cell_temp: float  # °C (raw/10)
    min_cell_vol: float  # V (raw/1000)
    max_cell_vol: float  # V (raw/1000)

    @classmethod
    def from_mqtt_payload(cls, data: dict) -> BmsModule:  # type: ignore[type-arg]
        """Build a BmsModule from a raw MQTT payload sub-dict."""
        return cls(
            module_sn=data.get("sn"),
            soc=float(data.get("soc", 0)),
            voltage=float(data.get("vol", 0)) / 1000,
            current=float(data.get("amp", 0)) / 1000,
            temp=float(data.get("temp", 0)) / 10,
            cycles=int(data.get("cycles", 0)),
            design_cap=int(data.get("designCap", 0)),
            full_cap=int(data.get("fullCap", 0)),
            remain_cap=int(data.get("remainCap", 0)),
            health=int(data.get("soh", 0)),
            min_cell_temp=float(data.get("minCellTemp", 0)) / 10,
            max_cell_temp=float(data.get("maxCellTemp", 0)) / 10,
            min_cell_vol=float(data.get("minCellVol", 0)) / 1000,
            max_cell_vol=float(data.get("maxCellVol", 0)) / 1000,
        )


@dataclass
class ExpansionBatteryModule:
    """Virtual sub-entity for expansion battery module (bms_slave, no own SN)."""

    slot_index: int
    soc: float
    voltage: float  # V (converted from mV via /1000)
    temp: float  # °C (raw/10)
    cycles: int
    full_cap: int
    remain_cap: int

    @classmethod
    def from_mqtt_payload(
        cls,
        slot: int,
        data: dict,  # type: ignore[type-arg]
    ) -> ExpansionBatteryModule:
        """Build an ExpansionBatteryModule from a raw MQTT payload sub-dict."""
        return cls(
            slot_index=slot,
            soc=float(data.get("soc", 0)),
            voltage=float(data.get("vol", 0)) / 1000,
            temp=float(data.get("temp", 0)) / 10,
            cycles=int(data.get("cycles", 0)),
            full_cap=int(data.get("fullCap", 0)),
            remain_cap=int(data.get("remainCap", 0)),
        )


@dataclass
class SolarInput:
    """MPPT solar input metrics (virtual sub-entity, no SN)."""

    input_watts: float
    voltage: float  # V (raw/10)
    current: float  # A (raw/100)

    @classmethod
    def from_mqtt_payload(cls, mppt: dict) -> SolarInput:  # type: ignore[type-arg]
        """Build a SolarInput from a raw MPPT sub-dict."""
        return cls(
            input_watts=float(mppt.get("inWatts", 0)),
            voltage=float(mppt.get("inVol", 0)) / 10,
            current=float(mppt.get("inAmp", 0)) / 100,
        )


@dataclass
class BatteryStatus:
    """Aggregated EcoFlow battery device status snapshot."""

    sn: str
    product_name: str
    online: bool
    soc: float
    remaining_charge_time_min: int
    remaining_discharge_time_min: int
    ac_input_watts: float
    ac_output_watts: float
    dc_output_watts: float
    mppt_input_watts: float
    usb_output_watts: float
    total_input_watts: float
    total_output_watts: float
    ac_output_enabled: bool
    dc_output_enabled: bool
    inverter_temp: float
    bms_modules: list[BmsModule]
    expansion_modules: list[ExpansionBatteryModule]
    solar_input: SolarInput | None
    updated_at: datetime | None

    @classmethod
    def from_mqtt_payload(cls, sn: str, data: dict) -> BatteryStatus:  # type: ignore[type-arg]
        """Build a BatteryStatus snapshot from a raw MQTT payload dict."""
        pd = data.get("pd") or {}
        inv = data.get("inv") or {}
        mppt_raw = data.get("mppt")
        mppt = mppt_raw or {}

        # Main BMS modules: keys starting with 'bms' but not 'bms_slave'
        bms_modules = [
            BmsModule.from_mqtt_payload(v)
            for k, v in data.items()
            if k.startswith("bms")
            and not k.startswith("bms_slave")
            and isinstance(v, dict)
        ]

        # Expansion (slave) battery modules: keys starting with 'bms_slave'
        slave_values = [
            v
            for k, v in data.items()
            if k.startswith("bms_slave") and isinstance(v, dict)
        ]
        expansion_modules = [
            ExpansionBatteryModule.from_mqtt_payload(slot, v)
            for slot, v in enumerate(slave_values)
        ]

        solar_input = (
            SolarInput.from_mqtt_payload(mppt_raw) if mppt_raw is not None else None
        )

        return cls(
            sn=sn,
            product_name="",
            online=True,
            soc=float(pd.get("soc", 0)),
            remaining_charge_time_min=int(pd.get("chgRemTime", 0)),
            remaining_discharge_time_min=int(pd.get("dsgRemTime", 0)),
            ac_input_watts=float(inv.get("inputWatts", 0)),
            ac_output_watts=float(inv.get("outputWatts", 0)),
            dc_output_watts=float(mppt.get("dcdc12vWatts", 0)),
            mppt_input_watts=float(mppt.get("inWatts", 0)),
            usb_output_watts=float(pd.get("usb1Watts", 0))
            + float(pd.get("usb2Watts", 0)),
            total_input_watts=float(pd.get("wattsInSum", 0)),
            total_output_watts=float(pd.get("wattsOutSum", 0)),
            ac_output_enabled=bool(inv.get("cfgAcEnabled", 0)),
            dc_output_enabled=bool(inv.get("cfgDcChgCurrent", 0)),
            inverter_temp=float(inv.get("invInTemp", 0)) / 10,
            bms_modules=bms_modules,
            expansion_modules=expansion_modules,
            solar_input=solar_input,
            updated_at=datetime.now(UTC),
        )
