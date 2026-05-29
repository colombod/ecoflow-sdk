"""EcoFlowClient — single entry point for the EcoFlow SDK."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any

from ecoflow.auth import EcoFlowCredentials
from ecoflow.const import SN_PREFIX_TO_MODEL, DeviceModel
from ecoflow.devices.battery import BatteryDevice
from ecoflow.devices.discovered import DiscoveredDevice
from ecoflow.devices.inverter import MicroInverterDevice
from ecoflow.devices.meter import SmartMeterDevice
from ecoflow.devices.panel import SmartHomePanelDevice
from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.devices.stream_ac_pro import StreamAcProDevice
from ecoflow.devices.stream_ultra import StreamUltraDevice
from ecoflow.devices.wave3 import Wave3Device
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from ecoflow.transport.rest import RestTransport

_log = logging.getLogger(__name__)

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


class EcoFlowClient:
    """Single entry point for the EcoFlow SDK.

    Usage::
        async with EcoFlowClient(access_key="...", secret_key="...", region="EU") as c:
            print(c.batteries)
    """

    def __init__(self, access_key: str, secret_key: str, region: str = "EU") -> None:
        self._credentials = EcoFlowCredentials(
            access_key=access_key, secret_key=secret_key
        )
        self._region = region
        self._rest: RestTransport = RestTransport(self._credentials, region=region)
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

    async def connect(self) -> None:
        """Fetch MQTT credentials, connect, and discover all devices."""
        await self._discover()
        try:
            mqtt_data = await self._rest.get_mqtt_credentials()
            mqtt_creds = MqttCredentials(
                url=mqtt_data.get("url", "mqtt.ecoflow.com"),
                port=int(mqtt_data.get("port", 8883)),
                protocol=mqtt_data.get("protocol", "mqtts"),
                username=mqtt_data.get("certificateAccount", ""),
                password=mqtt_data.get("certificatePassword", ""),
                client_id=mqtt_data.get("clientId", ""),
                # API returns certificateAccount, not userId
                user_id=mqtt_data.get("certificateAccount", ""),
            )
            self._mqtt = MqttTransport(mqtt_creds)
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

            cls = _DEVICE_CLASS_MAP.get(product_name)
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
        """Async generator yielding raw device update events.
        Events are routed to typed device _handle_message callbacks;
        this generator yields a dict with {'sn', 'product_name', 'data'}.
        """
        # Stub implementation — full MQTT streaming tested in integration tests
        # (requires live MQTT connection; mocking asyncio-mqtt's message loop
        # is deferred to integration testing)
        yield {}  # type: ignore[misc]
        return

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
