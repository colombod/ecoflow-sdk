"""SmartMeterDevice abstraction for EcoFlow Smart Meter devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.exceptions import EcoFlowDataUnavailableError
from ecoflow.models.meter import SmartMeterData


class SmartMeterDevice(BaseDevice):
    """EcoFlow Smart Meter device — read-only grid energy monitoring."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.data: SmartMeterData | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> SmartMeterData:
        """Fetch REST state; raise EcoFlowDataUnavailableError for an empty quota.

        BK21 meters normally return an empty REST quota and require MQTT.
        A failed refresh preserves the last MQTT snapshot and its receive times.
        """
        raw = await self._rest.get_quota(self.sn)
        if not raw:
            raise EcoFlowDataUnavailableError(
                "Smart Meter REST has no readings; use MQTT updates"
            )
        self._merge_telemetry(self._raw_data, raw)
        data = SmartMeterData.from_mqtt_payload(self.sn, self._raw_data)
        data.product_name = self.product_name
        self.data = data
        return self.data

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update data from an incoming MQTT payload, accumulating chunks."""
        if not data:
            return
        self._merge_telemetry(self._raw_data, data)
        self.data = SmartMeterData.from_mqtt_payload(sn, self._raw_data)
        self.data.product_name = self.product_name
        self._notify_callbacks(self.data)
