"""BaseDevice abstraction for EcoFlow devices."""

from __future__ import annotations

import asyncio
import functools
import itertools
import logging
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ecoflow.transport.mqtt import MqttTransport
    from ecoflow.transport.rest import RestTransport

_log = logging.getLogger(__name__)

# Monotonic per-process sequence for the command envelope ``id`` field.
_command_seq = itertools.count(1)

# Per-subscriber buffer for events(); oldest updates are dropped beyond this.
_EVENT_BUFFER = 100


def put_dropping_oldest(queue: asyncio.Queue[Any], item: Any) -> None:  # noqa: ANN401
    """Put *item* on *queue*, dropping the oldest entry if it is full."""
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(item)


class BaseDevice:
    """Base class for all EcoFlow device abstractions.

    Publishes commands via MQTT when connected, falls back to REST otherwise.
    """

    def __init__(
        self,
        sn: str,
        product_name: str,
        rest: RestTransport,
        mqtt: MqttTransport | None = None,
    ) -> None:
        self.sn = sn
        self.product_name = product_name
        self._rest = rest
        self._mqtt = mqtt
        self._callbacks: list[Callable[[Any], None]] = []
        # Internal sinks feeding events() / wait_for_update() queues.
        self._sinks: list[Callable[[Any], None]] = []
        self._last_updated: datetime | None = None

    async def _publish(self, payload: dict[str, Any]) -> None:
        """Publish a command to this device via MQTT set topic.

        Uses the official public-API topic /open/{user_id}/{sn}/set.

        QUIRK: every public-API set command carries the envelope fields
        ``from``, ``id``, ``version`` and ``sn`` (see AGENTS.md Quirk 13).
        They are filled in here when the payload does not already set them.
        Source: tolwi/hassio-ecoflow-cloud ``api/message.py`` JSONMessage.

        Raises:
            EcoFlowConnectionError: if MQTT is not connected.
        """
        from ecoflow.const import TOPIC_OPEN_SET
        from ecoflow.exceptions import EcoFlowConnectionError

        if self._mqtt is None or not self._mqtt.connected:
            raise EcoFlowConnectionError("MQTT not connected — cannot send command")
        topic = TOPIC_OPEN_SET.format(user_id=self._mqtt.creds.user_id, sn=self.sn)
        message: dict[str, Any] = {
            "from": "ecoflow-python",
            "id": str(next(_command_seq)),
            "version": "1.0",
            "sn": self.sn,
            **payload,
        }
        await self._mqtt.publish(topic, message)

    async def events(self) -> AsyncGenerator[Any, None]:
        """Async generator yielding status updates for this device.

        Yields the typed status dataclass on each MQTT update, in order.
        Each ``events()`` iterator gets its own buffer; if a consumer falls
        more than ``_EVENT_BUFFER`` updates behind, the oldest are dropped.

        Usage::
            async for event in device.events():
                print(event)
        """
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_EVENT_BUFFER)
        remove = self._add_sink(functools.partial(put_dropping_oldest, queue))
        try:
            while True:
                yield await queue.get()
        finally:
            remove()

    def _add_sink(self, sink: Callable[[Any], None]) -> Callable[[], None]:
        """Register an internal update sink; returns a function removing it."""
        self._sinks.append(sink)
        return lambda: self._sinks.remove(sink)

    async def wait_for_update(self) -> Any:  # noqa: ANN401
        """Wait for the next MQTT update and return the new status.

        Bound the wait with ``asyncio.timeout``::

            async with asyncio.timeout(60):
                status = await device.wait_for_update()
        """
        updates = self.events()
        try:
            return await anext(updates)
        finally:
            await updates.aclose()

    def _handle_message(self, sn: str, data: dict[str, Any]) -> None:
        """Route incoming MQTT payload — discard if older than cached state.

        Only strictly older messages are dropped: chunks of one state dump can
        share a timestamp on platforms with a coarse clock.
        """
        now = datetime.now(tz=UTC)
        if self._last_updated is not None and self._last_updated > now:
            _log.debug("Discarding stale message for %s", sn)
            return
        self._last_updated = now
        self._on_message(sn, data)

    def _on_message(self, sn: str, data: dict[str, Any]) -> None:
        """Process an accepted MQTT payload — override in subclasses."""

    def on_update(self, callback: Callable[[Any], None]) -> None:
        """Register a callback invoked on every device update."""
        self._callbacks.append(callback)

    def _notify_callbacks(self, status: Any) -> None:  # noqa: ANN401
        """Deliver the current status to on_update callbacks and event streams."""
        for cb in self._callbacks:
            try:
                cb(status)
            except Exception:
                _log.exception("Error in on_update callback for %s", self.sn)
        for sink in list(self._sinks):
            sink(status)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} sn={self.sn!r} product={self.product_name!r}>"
