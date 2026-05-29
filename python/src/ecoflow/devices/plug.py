"""SmartPlugDevice abstraction for EcoFlow Smart Plug devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.plug import SmartPlugData


class SmartPlugDevice(BaseDevice):
    """EcoFlow Smart Plug device with on/off/toggle/brightness controls."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.data: SmartPlugData | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> SmartPlugData:
        """Fetch current device state via REST and return a SmartPlugData."""
        raw = await self._rest.get_quota(self.sn)
        self.data = SmartPlugData.from_quota_payload(self.sn, raw)
        self.data.product_name = self.product_name
        return self.data

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update data from an incoming MQTT payload, accumulating chunks."""
        self._raw_data.update(data)
        self.data = SmartPlugData.from_mqtt_payload(sn, self._raw_data)
        self.data.product_name = self.product_name
        self._notify_callbacks(self.data)

    async def turn_on(self) -> None:
        """Turn the smart plug on."""
        await self._publish({"switch": 1})

    async def turn_off(self) -> None:
        """Turn the smart plug off."""
        await self._publish({"switch": 0})

    async def toggle(self) -> None:
        """Toggle the smart plug on or off.

        If device state is unknown, refreshes first.
        """
        if self.data is None:
            await self.refresh()
        if self.data and self.data.is_on:
            await self.turn_off()
        else:
            await self.turn_on()

    async def set_brightness(self, level: int) -> None:
        """Set the indicator LED brightness (0–100).

        Raises:
            ValueError: if level is not between 0 and 100 inclusive.
        """
        if not (0 <= level <= 100):
            raise ValueError(f"brightness level must be between 0 and 100, got {level}")
        await self._publish({"brightness": level})
