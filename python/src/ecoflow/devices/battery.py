"""BatteryDevice abstraction for EcoFlow PowerStation battery devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.battery import BatteryStatus


class BatteryDevice(BaseDevice):
    """EcoFlow battery device with charge/discharge controls."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.status: BatteryStatus | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> BatteryStatus:
        """Fetch current device state via REST and return a BatteryStatus."""
        data = await self._rest.get_quota(self.sn)
        status = BatteryStatus.from_mqtt_payload(self.sn, data)
        status.product_name = self.product_name
        self.status = status
        return self.status

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update status from an incoming MQTT payload, accumulating chunks."""
        self._raw_data.update(data)
        self.status = BatteryStatus.from_mqtt_payload(sn, self._raw_data)
        self.status.product_name = self.product_name
        self._notify_callbacks(self.status)

    async def set_ac_output(self, *, enabled: bool) -> None:
        """Enable or disable AC output."""
        await self._publish({"cfgAcEnabled": int(enabled)})

    async def set_dc_output(self, *, enabled: bool) -> None:
        """Enable or disable DC output."""
        await self._publish({"cfgDcEnabled": int(enabled)})

    async def set_charge_limit(self, *, soc_pct: int) -> None:
        """Set maximum charge limit (50–100%)."""
        if not (50 <= soc_pct <= 100):
            raise ValueError(f"soc_pct must be between 50 and 100, got {soc_pct}")
        await self._publish({"maxChgSoc": soc_pct})

    async def set_discharge_limit(self, *, soc_pct: int) -> None:
        """Set minimum discharge limit (0–30%)."""
        if not (0 <= soc_pct <= 30):
            raise ValueError(f"soc_pct must be between 0 and 30, got {soc_pct}")
        await self._publish({"minDsgSoc": soc_pct})

    async def set_ac_charging_power(self, *, watts: int) -> None:
        """Set AC charging power in watts."""
        await self._publish({"cfgAcChgPower": watts})
