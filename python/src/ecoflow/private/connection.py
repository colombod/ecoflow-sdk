"""Wave3Connection — MQTT connection for EcoFlow Wave 3 private API.

Uses email/password authentication (PrivateCredentials) and Protobuf decoding.
The public Developer API (accessKey/secretKey) does not support Wave 3 devices —
they return error 1006. Use this class instead.

Usage:
    from ecoflow.private import Wave3Connection

    async with Wave3Connection(
        email="me@example.com",
        password="my_password",
        device_sns=["AC71ZK1APJ410297"],
    ) as wave3:
        device = wave3.devices["AC71ZK1APJ410297"]
        await asyncio.sleep(5)   # wait for first MQTT push
        print(device.status.battery_soc)
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time

import aiomqtt

from ecoflow.devices.wave3 import Wave3Device
from ecoflow.private.auth import PrivateCredentials, login
from ecoflow.private.proto.decoder import decode

_log = logging.getLogger(__name__)

# Timeout for MQTT to connect and signal ready. Patched in tests.
_CONNECT_TIMEOUT_S: float = 15.0


class Wave3Connection:
    """Manages Wave 3 device connections via EcoFlow's private MQTT API.

    Authentication: email + password → PrivateCredentials (one-time login).
    Wire format: Protobuf (decoded via ecoflow.private.proto.decoder).
    MQTT broker: mqtt.ecoflow.com:8883 (TLS, NOT the public mqtt-e.ecoflow.com).
    Topic: /app/device/property/{sn} at QoS 1.

    QUIRK: The private broker is the same for EU and US accounts.
    The public API uses mqtt-e.ecoflow.com for EU — do not use that here.
    """

    def __init__(
        self,
        email: str,
        password: str,
        device_sns: list[str],
    ) -> None:
        self._email = email
        self._password = password
        self._sns = device_sns
        self.devices: dict[str, Wave3Device] = {}
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event = asyncio.Event()

    async def connect(self) -> None:
        """Authenticate, create Wave3Device instances, start the MQTT loop.

        Blocks until MQTT is connected and subscribed (up to _CONNECT_TIMEOUT_S).

        Raises:
            EcoFlowAuthError: if email/password are invalid.
            TimeoutError: if MQTT does not connect within _CONNECT_TIMEOUT_S.
        """
        creds = await login(self._email, self._password)
        self.devices = {
            sn: Wave3Device(sn=sn, product_name="Wave 3", rest=None) for sn in self._sns
        }
        self._task = asyncio.create_task(self._run(creds))
        try:
            await asyncio.wait_for(
                self._ready.wait(),
                timeout=_CONNECT_TIMEOUT_S,
            )
        except TimeoutError:
            if self._task and not self._task.done():
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            raise TimeoutError(
                f"Wave3 MQTT connection timed out after {_CONNECT_TIMEOUT_S:.0f}s"
            ) from None

    async def close(self) -> None:
        """Cancel the background MQTT task and wait for it to finish."""
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def __aenter__(self) -> Wave3Connection:
        """Call connect() and return self."""
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Call close() on context exit."""
        await self.close()

    async def _run(self, creds: PrivateCredentials) -> None:
        """Background MQTT loop — decodes Protobuf, dispatches to Wave3Device.

        Reconnects automatically with exponential backoff on any MQTT exception.
        Backoff: 1s → 2s → 4s → … → 300s cap.

        QUIRK: Uses aiomqtt directly, NOT the existing MqttTransport.
        MqttTransport calls json.loads() on every message and silently discards
        non-JSON content — which is every Wave 3 Protobuf message.
        """
        tls_ctx = ssl.create_default_context()
        backoff = 1.0

        while True:
            try:
                async with aiomqtt.Client(
                    hostname="mqtt.ecoflow.com",  # private broker — NOT mqtt-e
                    port=8883,
                    username=creds.certificate_account,
                    password=creds.certificate_password,
                    identifier=f"{creds.certificate_account}_{int(time.time())}",
                    keepalive=60,
                    tls_context=tls_ctx,
                ) as client:
                    for sn in self.devices:
                        await client.subscribe(f"/app/device/property/{sn}", qos=1)
                    self._ready.set()
                    backoff = 1.0  # reset on successful connect

                    async for message in client.messages:
                        sn = str(message.topic).rsplit("/", 1)[-1]
                        if sn in self.devices:
                            data = decode(bytes(message.payload))
                            if data:
                                self.devices[sn]._handle_message(sn, data)

            except asyncio.CancelledError:
                return  # clean shutdown — do not reconnect

            except Exception as exc:
                self._ready.clear()
                _log.warning(
                    "Wave3 MQTT connection lost (%s), retrying in %.0fs",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)
