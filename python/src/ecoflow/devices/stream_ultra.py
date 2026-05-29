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

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------

    def _stream_cmd(self, params: dict[str, Any]) -> dict[str, Any]:
        """Build a STREAM command envelope for the Public API."""
        return {
            "sn": self.sn,
            "cmdId": 17,
            "cmdFunc": 254,
            "params": params,
        }

    # ------------------------------------------------------------------
    # Existing commands (charge / discharge limits)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # New write commands (STREAM Public API cmdId=17 / cmdFunc=254 format)
    # ------------------------------------------------------------------

    async def set_relay2(self, *, on: bool) -> None:
        """Turn AC outlet 1 (relay2) on or off."""
        await self._publish(self._stream_cmd({"cfgRelay2Onoff": on}))

    async def set_relay3(self, *, on: bool) -> None:
        """Turn AC outlet 2 (relay3) on or off."""
        await self._publish(self._stream_cmd({"cfgRelay3Onoff": on}))

    async def set_grid_export(self, *, enabled: bool) -> None:
        """Enable or disable grid export (feed-in) mode."""
        await self._publish(self._stream_cmd({"cfgFeedGridMode": 2 if enabled else 1}))

    async def set_backup_reserve(self, *, soc_pct: int) -> None:
        """Set backup reserve SOC level (3–95 %).

        Raises:
            ValueError: if soc_pct is not between 3 and 95 inclusive.
        """
        if not 3 <= soc_pct <= 95:
            raise ValueError(f"backup_reserve must be 3–95, got {soc_pct}")
        await self._publish(self._stream_cmd({"cfgBackupReverseSoc": soc_pct}))

    async def set_self_powered_mode(self, *, enabled: bool) -> None:
        """Enable or disable self-powered mode (use solar/battery before grid)."""
        await self._publish(
            self._stream_cmd(
                {
                    "cfgEnergyStrategyOperateMode": {
                        "operateSelfPoweredOpen": enabled,
                    }
                }
            )
        )

    async def set_ai_schedule_mode(self, *, enabled: bool) -> None:
        """Enable or disable AI intelligent schedule mode."""
        await self._publish(
            self._stream_cmd(
                {
                    "cfgEnergyStrategyOperateMode": {
                        "operateIntelligentScheduleModeOpen": enabled,
                    }
                }
            )
        )
