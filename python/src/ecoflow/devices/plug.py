"""SmartPlugDevice abstraction for EcoFlow Smart Plug devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.plug import SmartPlugData


class SmartPlugDevice(BaseDevice):
    """EcoFlow Smart Plug device with on/off/toggle/brightness/max_watts controls."""

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
        """Turn the smart plug relay ON."""
        await self._publish(
            {
                "cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE",
                "params": {"plugSwitch": 1},
            }
        )

    async def turn_off(self) -> None:
        """Turn the smart plug relay OFF."""
        await self._publish(
            {
                "cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE",
                "params": {"plugSwitch": 0},
            }
        )

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

    async def set_brightness(self, brightness: int) -> None:
        """Set LED indicator brightness (0–1023 raw, maps to 0–100% in EcoFlow app).

        Raises:
            ValueError: if brightness is not between 0 and 1023 inclusive.
        """
        if not 0 <= brightness <= 1023:
            raise ValueError(f"brightness must be 0–1023, got {brightness}")
        await self._publish(
            {
                "cmdCode": "WN511_SOCKET_SET_BRIGHTNESS_PACK",
                "params": {"brightness": brightness},
            }
        )

    async def set_max_watts(self, max_watts: int) -> None:
        """Set maximum load power limit in Watts (0–2500W).

        Raises:
            ValueError: if max_watts is not between 0 and 2500 inclusive.
        """
        if not 0 <= max_watts <= 2500:
            raise ValueError(f"max_watts must be 0–2500, got {max_watts}")
        await self._publish(
            {
                "cmdCode": "WN511_SOCKET_SET_MAX_WATTS",
                "params": {"maxWatts": max_watts},
            }
        )
