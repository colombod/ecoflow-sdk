"""SmartHomePanelDevice abstraction for EcoFlow Smart Home Panel devices."""

from __future__ import annotations

from typing import Any

from ecoflow.devices.base import BaseDevice


class SmartHomePanelDevice(BaseDevice):
    """EcoFlow Smart Home Panel device — PARTIAL typed support.

    Field mapping is incomplete. Only the raw quota payload is surfaced
    today; no typed model exists yet. Fields are best-effort from limited
    community documentation.
    """

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.raw_fields: dict[str, Any] = {}  # partial — mapping unverified

    async def refresh(self) -> dict[str, Any]:
        """Fetch current device state via REST and return raw quota data.

        Returns raw quota data — no typed model yet (partial support).
        """
        self.raw_fields = await self._rest.get_quota(
            self.sn
        )  # partial — mapping unverified
        return self.raw_fields

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:
        """Update raw_fields from an incoming MQTT payload, accumulating chunks."""
        self.raw_fields.update(data)  # partial — mapping unverified
        self._notify_callbacks(self.raw_fields)
