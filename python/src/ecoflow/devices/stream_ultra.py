"""StreamUltraDevice — EcoFlow STREAM Ultra home energy system."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice
from ecoflow.models.stream_ultra import StreamUltraStatus


class StreamUltraDevice(BaseDevice):
    """Control and monitor an EcoFlow STREAM Ultra home energy system.

    Provides battery SOC, grid import/export, home load, and solar PV monitoring.
    """

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.status: StreamUltraStatus | None = None
        self._raw_data: dict[str, Any] = {}  # accumulate MQTT chunks

    async def refresh(self) -> StreamUltraStatus:
        """Fetch current device state via REST and return a StreamUltraStatus."""
        raw = await self._rest.get_quota(self.sn)
        self.status = StreamUltraStatus.from_quota_payload(self.sn, raw)
        self.status.product_name = self.product_name
        return self.status

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Update status from an incoming MQTT payload, accumulating chunks."""
        self._raw_data.update(data)
        self.status = StreamUltraStatus.from_quota_payload(sn, self._raw_data)
        self.status.product_name = self.product_name
        self._notify_callbacks(self.status)

    async def set_charge_limit(self, *, soc_pct: int) -> None:
        """Set maximum charge SOC (50–100 %).

        Raises:
            ValueError: if soc_pct is not between 50 and 100 inclusive.
        """
        if not 50 <= soc_pct <= 100:
            raise ValueError(f"charge_limit must be 50–100, got {soc_pct}")
        await self._publish({"cmsMaxChgSoc": soc_pct})

    async def set_discharge_limit(self, *, soc_pct: int) -> None:
        """Set minimum discharge SOC (0–30 %).

        Raises:
            ValueError: if soc_pct is not between 0 and 30 inclusive.
        """
        if not 0 <= soc_pct <= 30:
            raise ValueError(f"discharge_limit must be 0–30, got {soc_pct}")
        await self._publish({"cmsMinDsgSoc": soc_pct})
