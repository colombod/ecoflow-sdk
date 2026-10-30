"""Small structural interfaces consumed by device adapters.

The client owns discovery, certification and transport lifecycle. Devices need
only quota reads and command publishing, not the concrete HTTP/MQTT clients.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ecoflow.transport.mqtt import MqttCredentials


class QuotaReader(Protocol):
    """Read quota data without exposing HTTP or authentication machinery."""

    async def get_quota(self, sn: str) -> dict[str, Any]: ...


class CommandPublisher(Protocol):
    """The MQTT capabilities required by public-API command adapters."""

    @property
    def connected(self) -> bool: ...

    @property
    def creds(self) -> MqttCredentials: ...

    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...
