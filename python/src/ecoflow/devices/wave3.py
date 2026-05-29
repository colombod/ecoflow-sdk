"""Wave3Device abstraction for EcoFlow Wave 3 portable air conditioner."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.wave3 import Wave3Mode, Wave3Status


class Wave3Device(BaseDevice):
    """EcoFlow Wave 3 portable AC with mode/temperature/fan controls."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.status: Wave3Status | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> Wave3Status:
        """Fetch current device state via REST and return a Wave3Status."""
        raw = await self._rest.get_quota(self.sn)
        status = Wave3Status.from_mqtt_payload(self.sn, raw)
        status.product_name = self.product_name
        self.status = status
        return self.status

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update status from an incoming MQTT payload, accumulating chunks."""
        self._raw_data.update(data)
        self.status = Wave3Status.from_mqtt_payload(sn, self._raw_data)
        self.status.product_name = self.product_name
        self._notify_callbacks(self.status)

    async def turn_on(self) -> None:
        """Turn the Wave 3 AC on."""
        await self._publish({"powerMode": 1})

    async def turn_off(self) -> None:
        """Turn the Wave 3 AC off."""
        await self._publish({"powerMode": 0})

    async def set_mode(self, mode: Wave3Mode) -> None:
        """Set the operating mode (cool, heat, fan, dry, auto)."""
        await self._publish({"waveMode": int(mode)})

    async def set_temperature(self, temp_c: float) -> None:
        """Set the target temperature in °C (16.0–30.0).

        Raises:
            ValueError: if temp_c is outside the valid range.
        """
        if not (16.0 <= temp_c <= 30.0):
            raise ValueError(
                f"temperature must be between 16.0 and 30.0 °C, got {temp_c}"
            )
        await self._publish({"setTemp": int(temp_c * 10)})

    async def set_fan_speed(self, level: int) -> None:
        """Set the fan speed level.

        Args:
            level: 0=auto, 1=low, 2=medium, 3=high

        Raises:
            ValueError: if level is not 0, 1, 2, or 3.
        """
        if level not in (0, 1, 2, 3):
            raise ValueError(
                f"fan speed level must be 0 (auto), 1 (low), 2 (medium), or 3 (high),"
                f" got {level}"
            )
        await self._publish({"fanValue": level})
