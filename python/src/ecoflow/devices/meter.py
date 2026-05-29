"""SmartMeterDevice abstraction for EcoFlow Smart Meter devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.meter import SmartMeterData


class SmartMeterDevice(BaseDevice):
    """EcoFlow Smart Meter device — read-only grid energy monitoring."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.data: SmartMeterData | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> SmartMeterData:
        """Fetch current device state via REST and return a SmartMeterData."""
        raw = await self._rest.get_quota(self.sn)
        data = SmartMeterData.from_mqtt_payload(self.sn, raw)
        data.product_name = self.product_name
        self.data = data
        return self.data

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update data from an incoming MQTT payload, accumulating chunks."""
        self._raw_data.update(data)
        self.data = SmartMeterData.from_mqtt_payload(sn, self._raw_data)
        self.data.product_name = self.product_name
        self._notify_callbacks(self.data)
