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
import json
import logging
import ssl
import uuid

import aiomqtt

from ecoflow.const import TOPIC_DEVICE_SET
from ecoflow.devices.wave3 import Wave3Device
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.models.wave3 import Wave3Mode
from ecoflow.private.auth import PrivateCredentials, login
from ecoflow.private.proto.decoder import decode
from ecoflow.private.proto.encoder import build_command

_log = logging.getLogger(__name__)

# Timeout for MQTT to connect and signal ready. Patched in tests.
_CONNECT_TIMEOUT_S: float = 15.0


class Wave3Connection:
    """Manages Wave 3 device connections via EcoFlow's private MQTT API.

    Authentication: email + password → PrivateCredentials (one-time login).
    Wire format: Protobuf (decoded via ecoflow.private.proto.decoder).
    MQTT broker: mqtt.ecoflow.com:8883 (TLS, NOT the public mqtt-e.ecoflow.com).
    Subscribe topic: /app/device/property/{sn} at QoS 1.
    Command topic: /app/{user_id}/{sn}/thing/property/set at QoS 1.

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
        self._publish_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self._user_id: str = ""  # set after login in connect()

    async def connect(self) -> None:
        """Authenticate, create Wave3Device instances, start the MQTT loop.

        Blocks until MQTT is connected and subscribed (up to _CONNECT_TIMEOUT_S).

        Raises:
            EcoFlowAuthError: if email/password are invalid.
            TimeoutError: if MQTT does not connect within _CONNECT_TIMEOUT_S.
        """
        creds = await login(self._email, self._password)
        self._user_id = creds.user_id
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
                client_id = f"ANDROID_{uuid.uuid4().hex.upper()}_{creds.user_id}"
                async with aiomqtt.Client(
                    hostname="mqtt.ecoflow.com",
                    port=8883,
                    username=creds.certificate_account,
                    password=creds.certificate_password,
                    identifier=client_id,
                    keepalive=60,
                    tls_context=tls_ctx,
                ) as client:
                    for sn in self.devices:
                        await client.subscribe(f"/app/device/property/{sn}", qos=1)
                    # Trigger immediate state dump from each device.
                    # Without this, the Wave 3 is silent until the next heartbeat.
                    # QUIRK: GET published to /app/{user_id}/{sn}/thing/property/get
                    # triggers the device to dump its full state on
                    # /app/device/property/{sn}.
                    for sn in self.devices:
                        get_topic = f"/app/{creds.user_id}/{sn}/thing/property/get"
                        get_payload = json.dumps(
                            {
                                "version": "1.0",
                                "sn": sn,
                                "moduleType": 0,
                                "operateType": "get",
                                "params": {},
                            }
                        ).encode()
                        await client.publish(get_topic, get_payload, qos=1)
                    self._ready.set()
                    backoff = 1.0
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._receive_loop(client))
                        tg.create_task(self._publish_loop(client, creds.user_id))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._ready.clear()
                _log.warning(
                    "Wave3 MQTT connection lost (%s), retrying in %.0fs", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)

    async def _receive_loop(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            sn = str(message.topic).rsplit("/", 1)[-1]
            if sn in self.devices:
                data = decode(bytes(message.payload))
                if data:
                    self.devices[sn]._handle_message(sn, data)

    async def _publish_loop(self, client: aiomqtt.Client, user_id: str) -> None:
        while True:
            sn, payload = await self._publish_queue.get()
            topic = TOPIC_DEVICE_SET.format(user_id=user_id, sn=sn)
            await client.publish(topic, payload, qos=1)
            self._publish_queue.task_done()

    # ---------------------------------------------------------------------------
    # High-level write commands
    # ---------------------------------------------------------------------------

    async def send_raw(self, sn: str, payload: bytes) -> None:
        """Enqueue a raw Protobuf payload for publishing to the device topic.

        Args:
            sn: Device serial number.
            payload: Serialised Wave3SetMessage bytes.

        Raises:
            EcoFlowConnectionError: if the MQTT connection is not ready.
            ValueError: if sn is not a registered device.
        """
        if not self._ready.is_set():
            raise EcoFlowConnectionError("Wave3 MQTT connection is not ready")
        if sn not in self.devices:
            raise ValueError(f"Unknown device SN: {sn!r}")
        await self._publish_queue.put((sn, payload))

    async def turn_on(self, sn: str) -> None:
        """Turn the device on (cfg_main_power=True)."""
        await self.send_raw(sn, build_command(sn, cfg_main_power=True))

    async def turn_off(self, sn: str) -> None:
        """Pause the device (cfg_sys_pause=True)."""
        await self.send_raw(sn, build_command(sn, cfg_sys_pause=True))

    async def set_mode(self, sn: str, mode: Wave3Mode) -> None:
        """Set the operating mode.

        Args:
            sn: Device serial number.
            mode: Desired Wave3Mode (must not be NONE — use turn_off() instead).

        Raises:
            ValueError: if mode is Wave3Mode.NONE.
        """
        if mode == Wave3Mode.NONE:
            raise ValueError("Use turn_off() to stop the device, not set_mode(NONE)")
        await self.send_raw(
            sn,
            build_command(sn, cfg_main_power=True, cfg_wave_operating_mode=int(mode)),
        )

    async def set_temperature(self, sn: str, temp_c: float) -> None:
        """Set the target temperature setpoint (16.0–30.0 °C).

        Raises:
            ValueError: if temp_c is outside the supported range.
        """
        if not 16.0 <= temp_c <= 30.0:
            raise ValueError(f"Temperature {temp_c} out of range (16.0–30.0 °C)")
        await self.send_raw(sn, build_command(sn, cfg_temp_set=float(temp_c)))

    async def set_fan_speed(self, sn: str, level: int) -> None:
        """Set the fan speed level (1–5).

        Maps: 1→20, 2→40, 3→60, 4→80, 5→100 (raw protocol values).

        Raises:
            ValueError: if level is not in range(1, 6).
        """
        if level not in range(1, 6):
            raise ValueError(f"Fan speed level {level} out of range (1–5)")
        raw = level * 20
        await self.send_raw(sn, build_command(sn, cfg_airflow_speed=raw))

    async def set_humidity_target(self, sn: str, pct: float) -> None:
        """Set the target humidity setpoint (40.0–80.0 %).

        Raises:
            ValueError: if pct is outside the supported range.
        """
        if not 40.0 <= pct <= 80.0:
            raise ValueError(f"Humidity target {pct} out of range (40.0–80.0 %)")
        await self.send_raw(sn, build_command(sn, cfg_humi_set=float(pct)))

    async def set_charge_limit(self, sn: str, soc_pct: int) -> None:
        """Set the maximum charge SOC limit (50–100 %).

        Raises:
            ValueError: if soc_pct is outside the supported range.
        """
        if not 50 <= soc_pct <= 100:
            raise ValueError(f"Charge limit {soc_pct} out of range (50–100 %)")
        await self.send_raw(sn, build_command(sn, cmsMaxChgSoc=soc_pct))

    async def set_discharge_limit(self, sn: str, soc_pct: int) -> None:
        """Set the minimum discharge SOC limit (0–30 %).

        Raises:
            ValueError: if soc_pct is outside the supported range.
        """
        if not 0 <= soc_pct <= 30:
            raise ValueError(f"Discharge limit {soc_pct} out of range (0–30 %)")
        await self.send_raw(sn, build_command(sn, cmsMinDsgSoc=soc_pct))
