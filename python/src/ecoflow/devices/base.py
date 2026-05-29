"""BaseDevice abstraction for EcoFlow devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ecoflow.transport.mqtt import _MqttClient
    from ecoflow.transport.rest import _RestClient

_log = logging.getLogger(__name__)


class BaseDevice:
    """Base class for all EcoFlow device abstractions.

    Publishes commands via MQTT when connected, falls back to REST otherwise.
    """

    def __init__(
        self,
        sn: str,
        product_name: str,
        rest: _RestClient,
        mqtt: _MqttClient | None = None,
    ) -> None:
        self.sn = sn
        self.product_name = product_name
        self._rest = rest
        self._mqtt = mqtt
        self._callbacks: list[Callable[[Any], None]] = []
        self._last_event: Any = None
        self._last_updated: datetime | None = None

    async def _publish(self, params: dict[str, Any]) -> None:
        """Send a command via MQTT if connected, otherwise fall back to REST."""
        if self._mqtt is not None and self._mqtt._connected:
            from ecoflow.const import TOPIC_DEVICE_SET

            topic = TOPIC_DEVICE_SET.format(
                user_id=self._mqtt._creds.user_id,
                sn=self.sn,
            )
            await self._mqtt.publish(topic, {"params": params})
        else:
            await self._rest.set_quota(self.sn, params)

    async def events(self) -> AsyncGenerator[Any, None]:
        """Async generator yielding status updates for this device.

        Yields the typed status dataclass on each MQTT update.

        Usage::
            async for event in device.events():
                print(event)
        """
        while True:
            await asyncio.sleep(0.1)
            if self._last_event is not None:
                yield self._last_event
                self._last_event = None

    def _handle_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Route incoming MQTT payload — discard if older than cached state."""
        now = datetime.now(tz=UTC)
        if self._last_updated is not None and self._last_updated >= now:
            _log.debug("Discarding stale message for %s", sn)
            return
        self._last_updated = now
        self._on_message(sn, data)

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:  # type: ignore[type-arg]
        """Process an accepted MQTT payload — override in subclasses."""

    def on_update(self, callback: Callable[[Any], None]) -> None:
        """Register a callback invoked on every device update."""
        self._callbacks.append(callback)

    def _notify_callbacks(self, status: Any) -> None:  # noqa: ANN401
        """Invoke all registered callbacks with the current device status."""
        for cb in self._callbacks:
            try:
                cb(status)
            except Exception:
                _log.exception("Error in on_update callback for %s", self.sn)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} sn={self.sn!r} product={self.product_name!r}>"
