"""Wave3Device abstraction for EcoFlow Wave 3 portable air conditioner."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.wave3 import Wave3Mode, Wave3Status

if TYPE_CHECKING:
    from ecoflow.transport.mqtt import MqttTransport
    from ecoflow.transport.rest import RestTransport

_log = logging.getLogger(__name__)


class Wave3Device(BaseDevice):
    """EcoFlow Wave 3 portable AC with mode/temperature/fan controls."""

    # Wave3Device allows rest=None for the private MQTT-only API path.
    # Override the base class type to reflect this valid configuration.
    _rest: RestTransport | None

    def __init__(
        self,
        sn: str,
        product_name: str,
        rest: RestTransport | None = None,
        mqtt: MqttTransport | None = None,
    ) -> None:
        super().__init__(
            sn=sn,
            product_name=product_name,
            rest=rest,  # type: ignore[arg-type]  # Wave3Device supports rest=None
            mqtt=mqtt,
        )
        self.status: Wave3Status | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> Wave3Status:
        """Fetch current Wave 3 status via REST.

        NOTE: Wave 3 returns error 1006 from the public REST API
        (device is not allowed to get device info). When this happens,
        a minimal status with online=True is returned with all reading
        fields at defaults. Data arrives via MQTT on the private API only.

        NOTE: rest=None is valid for the private API path — Wave3Connection
        passes rest=None and data arrives via MQTT only.
        """
        if self._rest is None:
            # Private API path — no REST quota available for Wave 3.
            # Return current status if available, otherwise return minimal status.
            if self.status is None:
                self.status = Wave3Status(
                    sn=self.sn,
                    product_name=self.product_name,
                    online=True,
                )
            return self.status
        try:
            raw = await self._rest.get_quota(self.sn)
            self.status = Wave3Status.from_mqtt_payload(raw)
            self.status.sn = self.sn
            self.status.product_name = self.product_name
        except Exception as exc:
            # Wave 3 public API limitation — return minimal status
            _log.debug(
                "Wave 3 REST quota not available (%s): %s — returning minimal status",
                self.sn,
                exc,
            )
            self.status = Wave3Status(
                sn=self.sn,
                product_name=self.product_name,
                online=True,  # device is online (confirmed from device list)
                is_on=False,  # default — no data available from public API
            )
        return self.status

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update status from an incoming MQTT payload, accumulating chunks."""
        self._raw_data.update(data)
        # QUIRK (seen live 2026-09-28): the first messages after connect are
        # partial and lack the battery level, which then read as 0 % / off for
        # ~20 s. Publish nothing until the state dump with the SOC has arrived.
        if (
            "bms_batt_soc" not in self._raw_data
            and "cms_batt_soc" not in self._raw_data
        ):
            return
        self.status = Wave3Status.from_mqtt_payload(self._raw_data)
        self.status.sn = sn
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
            level: 0=auto, 1=low, 2=medium, 3=high.

        NOTE: This scale (0–3) is different from Wave3Status.fan_level (1–5),
        which is a read-only status field mapped from the raw airflow_speed.
        Do not pass Wave3Status.fan_level directly to this method.

        Raises:
            ValueError: if level is not 0, 1, 2, or 3.
        """
        if level not in (0, 1, 2, 3):
            raise ValueError(
                f"fan speed level must be 0 (auto), 1 (low), 2 (medium), or 3 (high),"
                f" got {level}"
            )
        await self._publish({"fanValue": level})
