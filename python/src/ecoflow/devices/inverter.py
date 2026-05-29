"""MicroInverterDevice abstraction for EcoFlow PowerStream micro-inverter devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.meter import SmartMeterData


class MicroInverterDevice(BaseDevice):
    """EcoFlow PowerStream microinverter with feed-in power control.

    NOTE: PowerStream 600W and 800W share productName 'PowerStream' —
    indistinguishable via API, no workaround.
    """

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        # Reuses SmartMeterData for grid-side telemetry until a dedicated
        # PowerStream model is wired up in a later phase.
        self.data: SmartMeterData | None = None

    async def refresh(self) -> SmartMeterData:
        """Fetch current device state via REST and return a SmartMeterData."""
        raw = await self._rest.get_quota(self.sn)
        data = SmartMeterData.from_mqtt_payload(self.sn, raw)
        data.product_name = self.product_name
        self.data = data
        return self.data

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update data from an incoming MQTT payload."""
        self.data = SmartMeterData.from_mqtt_payload(sn, data)
        self.data.product_name = self.product_name
        self._notify_callbacks(self.data)

    async def set_feed_in_power(self, *, watts: int) -> None:
        """Set the feed-in power in watts (0–800).

        Raises:
            ValueError: if watts is not between 0 and 800 inclusive.
        """
        if not (0 <= watts <= 800):
            raise ValueError(
                f"feed-in power must be between 0 and 800 watts, got {watts}"
            )
        await self._publish({"feedInPower": watts})
