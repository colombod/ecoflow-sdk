"""EcoFlow MQTT transport — private implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import aiomqtt

from ecoflow.const import (
    ECOFLOW_MQTT_KEEPALIVE,
    MQTT_CONNECT_TIMEOUT_S,
    TOPIC_OPEN_QUOTA,
)
from ecoflow.exceptions import EcoFlowConnectionError

_log = logging.getLogger(__name__)

MessageCallback = Callable[[str, dict], None]


@dataclass(frozen=True)
class MqttCredentials:
    url: str
    port: int
    protocol: str
    username: str
    password: str
    client_id: str
    user_id: str


class _MqttClient:
    """Private async MQTT client with TLS and exponential backoff reconnection.

    Connection is maintained by a long-lived background asyncio Task that owns
    the ``async with aiomqtt.Client(...)`` context.  ``connect()`` starts that
    task and waits until the broker confirms the session is live.
    """

    def __init__(
        self,
        credentials: MqttCredentials,
        connect_timeout: int = MQTT_CONNECT_TIMEOUT_S,
    ) -> None:
        self._creds = credentials
        self._timeout = connect_timeout
        # Maps SN → (topic_template, [callbacks])
        self._subscriptions: dict[str, tuple[str, list[MessageCallback]]] = {}
        self._connected = False
        self._ready = asyncio.Event()  # set when broker confirms connection
        self._run_task: asyncio.Task[None] | None = None
        self._client: Any = None  # live aiomqtt.Client set inside _run()

    def on_message(
        self,
        sn: str,
        callback: MessageCallback,
        topic_template: str = TOPIC_OPEN_QUOTA,
    ) -> None:
        """Register a callback for messages from device *sn*.

        Args:
            sn: Serial number of the device to subscribe to.
            callback: Callable receiving (sn, payload_dict).
            topic_template: MQTT topic template with {user_id} and {sn} placeholders.
                Defaults to TOPIC_OPEN_QUOTA — the correct topic for the official
                Developer API (accessKey/secretKey). Use TOPIC_DEVICE_PROPERTY for
                the legacy undocumented email/password API.
        """
        if sn not in self._subscriptions:
            self._subscriptions[sn] = (topic_template, [])
        self._subscriptions[sn][1].append(callback)
        # If already connected, subscribe immediately on the live client.
        if self._connected and self._client is not None:
            topic = topic_template.format(user_id=self._creds.user_id, sn=sn)
            asyncio.create_task(self._client.subscribe(topic, qos=1))

    async def connect(self) -> None:
        """Start the background MQTT task and wait for broker confirmation."""
        self._ready.clear()
        self._run_task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=float(self._timeout))
        except TimeoutError:
            if self._run_task:
                self._run_task.cancel()
                try:
                    await self._run_task
                except (asyncio.CancelledError, Exception):
                    pass
            raise EcoFlowConnectionError(
                f"MQTT connection timed out after {self._timeout}s"
            ) from None

    async def disconnect(self) -> None:
        """Cancel the background task and reset state."""
        self._connected = False
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        self._run_task = None
        self._client = None

    async def publish(self, topic: str, payload: dict) -> None:  # type: ignore[type-arg]
        if not self._connected or self._client is None:
            raise EcoFlowConnectionError("MQTT not connected")
        await self._client.publish(topic, json.dumps(payload), qos=1)

    async def _run(self) -> None:
        """Background task: own the aiomqtt connection and reconnect on failure."""
        tls_context = ssl.create_default_context()
        backoff = 1.0
        backoff_max = 300.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self._creds.url,
                    port=self._creds.port,
                    username=self._creds.username,
                    password=self._creds.password,
                    identifier=self._creds.client_id,
                    keepalive=ECOFLOW_MQTT_KEEPALIVE,
                    tls_context=tls_context,
                ) as client:
                    self._client = client
                    self._connected = True
                    backoff = 1.0

                    # Subscribe to all SNs registered before or after connect().
                    # Each SN has its own topic template stored in _subscriptions.
                    for sn, (topic_template, _callbacks) in self._subscriptions.items():
                        topic = topic_template.format(
                            user_id=self._creds.user_id, sn=sn
                        )
                        await client.subscribe(topic, qos=1)

                    self._ready.set()  # unblock connect()
                    _log.info(
                        "MQTT connected to %s:%d", self._creds.url, self._creds.port
                    )

                    async for message in client.messages:
                        try:
                            payload = json.loads(message.payload)
                        except json.JSONDecodeError:
                            _log.debug("Non-JSON MQTT payload on %s", message.topic)
                            continue
                        await self._dispatch_message(str(message.topic), payload)

            except asyncio.CancelledError:
                break  # clean shutdown requested — exit immediately

            except Exception as exc:
                self._connected = False
                self._client = None
                _log.warning(
                    "MQTT connection lost (%s), retrying in %.0fs", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, backoff_max)

        self._connected = False
        self._client = None

    async def _dispatch_message(self, topic: str, payload: dict) -> None:  # type: ignore[type-arg]
        """Route a decoded payload to registered callbacks by SN.

        Handles both topic patterns:
          /open/{user_id}/{sn}/quota  → SN is at index -2 (primary)
          /app/device/property/{sn}   → SN is at index -1 (legacy fallback)
        """
        parts = topic.split("/")
        # Try second-to-last first — covers /open/{user_id}/{sn}/quota
        sn = parts[-2] if len(parts) >= 2 else parts[-1]
        # If second-to-last doesn't match any subscription, fall back to last segment
        if sn not in self._subscriptions and len(parts) >= 1:
            sn = parts[-1]
        for registered_sn, (_template, callbacks) in self._subscriptions.items():
            if registered_sn == sn:
                for cb in callbacks:
                    try:
                        cb(sn, payload)
                    except Exception:
                        _log.exception("Error in MQTT callback for %s", sn)

    async def __aenter__(self) -> _MqttClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.disconnect()
