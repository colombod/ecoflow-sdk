"""EcoFlowClient — single entry point for the EcoFlow SDK."""

from __future__ import annotations

import asyncio
import functools
import hashlib as _hashlib
import logging
from collections.abc import AsyncGenerator, Callable
from types import TracebackType
from typing import Any

from ecoflow.auth import EcoFlowCredentials
from ecoflow.const import SN_PREFIX_TO_MODEL, DeviceModel
from ecoflow.devices.base import BaseDevice, put_dropping_oldest
from ecoflow.devices.battery import BatteryDevice
from ecoflow.devices.discovered import DiscoveredDevice
from ecoflow.devices.inverter import MicroInverterDevice
from ecoflow.devices.meter import SmartMeterDevice
from ecoflow.devices.panel import SmartHomePanelDevice
from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.devices.stream_ac_pro import StreamAcProDevice
from ecoflow.devices.stream_ultra import StreamUltraDevice
from ecoflow.devices.wave3 import Wave3Device
from ecoflow.endpoints import Endpoints
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from ecoflow.transport.rest import RestTransport

_log = logging.getLogger(__name__)

# Buffer for EcoFlowClient.events(); oldest updates are dropped beyond this.
_EVENT_BUFFER = 1000


def _forward(
    queue: asyncio.Queue[dict[str, Any]],
    device: BaseDevice,
    status: Any,  # noqa: ANN401
) -> None:
    put_dropping_oldest(
        queue, {"sn": device.sn, "product_name": device.product_name, "data": status}
    )


# Map productName → device class
_DEVICE_CLASS_MAP: dict[str, type] = {
    DeviceModel.DELTA_PRO.value: BatteryDevice,
    DeviceModel.DELTA_PRO_3.value: BatteryDevice,
    DeviceModel.DELTA_2.value: BatteryDevice,
    DeviceModel.DELTA_2_MAX.value: BatteryDevice,
    DeviceModel.RIVER_PRO.value: BatteryDevice,
    DeviceModel.RIVER_2.value: BatteryDevice,
    DeviceModel.RIVER_2_MAX.value: BatteryDevice,
    DeviceModel.RIVER_2_PRO.value: BatteryDevice,
    DeviceModel.POWER_STREAM.value: MicroInverterDevice,
    DeviceModel.SMART_PLUG.value: SmartPlugDevice,
    DeviceModel.SMART_METER.value: SmartMeterDevice,
    DeviceModel.STREAM_ULTRA.value: StreamUltraDevice,
    DeviceModel.STREAM_AC_PRO.value: StreamAcProDevice,
    DeviceModel.WAVE_3.value: Wave3Device,
    DeviceModel.SMART_HOME_PANEL_2.value: SmartHomePanelDevice,
    DeviceModel.WAVE_2.value: SmartHomePanelDevice,  # partial, best-effort
    DeviceModel.SMART_GENERATOR.value: SmartHomePanelDevice,  # partial, best-effort
}

# QUIRK: productName casing is not consistent across devices/firmware
# (e.g. "Delta Pro 3", "WAVE 2" per tolwi/hassio-ecoflow-cloud registry),
# so routing matches case-insensitively.
_DEVICE_CLASS_BY_NAME: dict[str, type] = {
    name.casefold(): cls for name, cls in _DEVICE_CLASS_MAP.items()
}


class EcoFlowClient:
    """Single entry point for the EcoFlow SDK.

    Usage::
        async with EcoFlowClient(access_key="...", secret_key="...", region="EU") as c:
            print(c.batteries)
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        region: str = "EU",
        *,
        enable_mqtt: bool = True,
        endpoints: Endpoints | None = None,
    ) -> None:
        """Create a client.

        Args:
            enable_mqtt: Set False for REST-only use (``refresh()`` reads, no
                live updates or commands). REST-only never opens an MQTT
                session, so it cannot displace another integration (e.g. Home
                Assistant) using the same keys — see AGENTS.md Quirk 2.
            endpoints: Where to connect. ``None`` reads ``Endpoints.from_env()``
                (``ECOFLOW_REST_BASE`` / ``ECOFLOW_CA_FILE``), so any app can be
                pointed at a digital twin without code changes.
        """
        self._enable_mqtt = enable_mqtt
        self._credentials = EcoFlowCredentials(
            access_key=access_key, secret_key=secret_key
        )
        self._region = region
        self.endpoints = endpoints if endpoints is not None else Endpoints.from_env()
        self._rest: RestTransport = RestTransport(
            self._credentials, region=region, endpoints=self.endpoints
        )
        self._mqtt: MqttTransport | None = None

        # Typed device collections — populated on connect()
        self.batteries: list[BatteryDevice] = []
        self.plugs: list[SmartPlugDevice] = []
        self.meters: list[SmartMeterDevice] = []
        self.wave3_units: list[Wave3Device] = []
        self.inverters: list[MicroInverterDevice] = []
        self.stream_units: list[StreamUltraDevice] = []
        self.unknown_devices: list[DiscoveredDevice] = []

        # Internal: all typed devices (for MQTT subscription routing)
        self._all_typed: list[Any] = []

    # ------------------------------------------------------------------
    # Public read-only properties
    # ------------------------------------------------------------------

    @property
    def mqtt_connected(self) -> bool:
        """Whether the MQTT transport is currently connected."""
        return self._mqtt is not None and self._mqtt.connected

    @property
    def mqtt_subscriptions(self) -> frozenset[str]:
        """Return the set of device SNs with active MQTT subscriptions."""
        if self._mqtt is None:
            return frozenset()
        return frozenset(self._mqtt.subscriptions)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Discover all devices, then fetch MQTT credentials and connect.

        With ``enable_mqtt=False`` only discovery runs.
        """
        await self._discover()
        if not self._enable_mqtt:
            _log.info("REST-only mode — MQTT disabled")
            return
        try:
            mqtt_data = await self._rest.get_mqtt_credentials()
            # QUIRK: EcoFlow MQTT broker allows ~10 unique client IDs per day per
            # account. Random UUIDs burn this quota instantly (one per restart).
            # A stable, deterministic ID reuses the same slot on every reconnect.
            # Source: EcoFlow community reports (ioBroker,
            # hassio-ecoflow-cloud issue trackers).
            _account = mqtt_data.get("certificateAccount", "")
            # Derive a stable ID: short hash of the account so it's always the
            # same across restarts, but doesn't expose the full account string.
            _stable_suffix = _hashlib.sha256(_account.encode()).hexdigest()[:12]
            client_id = mqtt_data.get("clientId") or f"ecoflow-sdk-{_stable_suffix}"
            mqtt_creds = MqttCredentials(
                url=mqtt_data.get("url", "mqtt.ecoflow.com"),
                port=int(mqtt_data.get("port", 8883)),
                protocol=mqtt_data.get("protocol", "mqtts"),
                username=mqtt_data.get("certificateAccount", ""),
                password=mqtt_data.get("certificatePassword", ""),
                client_id=client_id,
                # API returns certificateAccount, not userId
                user_id=mqtt_data.get("certificateAccount", ""),
            )
            self._mqtt = MqttTransport(
                mqtt_creds, ssl_context=self.endpoints.ssl_context()
            )
            # Backfill the mqtt reference into all devices.  Devices were
            # created during _discover() before MqttTransport existed, so
            # their _mqtt attribute is still None.  Without this, _publish()
            # always raises EcoFlowConnectionError even when MQTT is live.
            for device in self._all_typed:
                device._mqtt = self._mqtt  # noqa: SLF001
            # Register callbacks BEFORE connect() so _run() subscribes to all
            # devices in one shot and captures the broker's initial state dump.
            for device in self._all_typed:
                if hasattr(device, "_handle_message"):
                    self._mqtt.on_message(device.sn, device._handle_message)  # noqa: SLF001
            await self._mqtt.connect()
        except Exception as exc:
            _log.warning("MQTT unavailable — REST-only mode: %s", exc)

    async def disconnect(self) -> None:
        """Close MQTT and REST connections."""
        if self._mqtt is not None:
            await self._mqtt.disconnect()
        await self._rest.close()

    async def _discover(self) -> None:
        """Fetch device list and populate typed collections."""
        devices = await self._rest.list_devices()
        self.batteries = []
        self.plugs = []
        self.meters = []
        self.wave3_units = []
        self.inverters = []
        self.stream_units = []
        self.unknown_devices = []
        self._all_typed = []

        for raw in devices:
            sn = raw.get("sn", "")
            # Primary routing: use productName if present.
            # Fallback: use SN prefix (4 chars) when productName absent.
            # Real API omits productName for BK-series STREAM devices.
            product_name = raw.get("productName", "") or ""
            if not product_name:
                sn_prefix = sn[:4] if len(sn) >= 4 else ""
                product_name = SN_PREFIX_TO_MODEL.get(sn_prefix, "")

            cls = _DEVICE_CLASS_BY_NAME.get(product_name.casefold())
            if cls is None:
                self.unknown_devices.append(
                    DiscoveredDevice(
                        sn=sn,
                        product_name=product_name,
                        online=bool(raw.get("online", 0)),
                        raw=raw,
                    )
                )
                continue
            device = cls(
                sn=sn, product_name=product_name, rest=self._rest, mqtt=self._mqtt
            )
            self._all_typed.append(device)
            if isinstance(device, BatteryDevice):
                self.batteries.append(device)
            elif isinstance(device, SmartPlugDevice):
                self.plugs.append(device)
            elif isinstance(device, SmartMeterDevice):
                self.meters.append(device)
            elif isinstance(device, Wave3Device):
                self.wave3_units.append(device)
            elif isinstance(device, MicroInverterDevice):
                self.inverters.append(device)
            elif isinstance(device, StreamUltraDevice):
                self.stream_units.append(device)

    async def events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator yielding updates from every typed device.

        Each item is ``{"sn": ..., "product_name": ..., "data": <status>}``
        where ``data`` is the device's typed status object.  Devices must be
        discovered (``connect()``) before iterating.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_EVENT_BUFFER)
        removers: list[Callable[[], None]] = []
        for device in self._all_typed:
            removers.append(
                device._add_sink(functools.partial(_forward, queue, device))
            )  # noqa: SLF001
        try:
            while True:
                yield await queue.get()
        finally:
            for remove in removers:
                remove()

    async def __aenter__(self) -> EcoFlowClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.disconnect()
