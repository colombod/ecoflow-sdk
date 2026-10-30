"""Devices work with the read/publish capabilities, without full transports."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from ecoflow.devices.base import BaseDevice
from ecoflow.devices.meter import SmartMeterDevice
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.transport.mqtt import MqttCredentials
from ecoflow.transport.protocols import CommandPublisher, QuotaReader


@dataclass
class MemoryQuota:
    requests: list[str] = field(default_factory=list[str])

    async def get_quota(self, sn: str) -> dict[str, Any]:
        self.requests.append(sn)
        return {"powGetSysGrid": 0}


@dataclass
class MemoryPublisher:
    connected: bool = True
    creds: MqttCredentials = field(
        default_factory=lambda: MqttCredentials(
            "offline.invalid", 8883, "mqtts", "u", "p", "c", "test"
        )
    )
    sent: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.sent.append((topic, payload))


async def test_meter_uses_only_quota_reader() -> None:
    concrete = MemoryQuota()
    reader: QuotaReader = concrete  # structural contract checked by Pyright
    device = SmartMeterDevice(sn="BK21TEST", product_name="meter", rest=reader)
    data = await device.refresh()
    assert data.grid_power_watts == 0
    assert "powGetSysGrid" in device.field_received_at
    assert concrete.requests == [device.sn]


async def test_command_uses_only_publisher_and_never_falls_back_to_rest() -> None:
    quota = MemoryQuota()
    concrete = MemoryPublisher()
    publisher: CommandPublisher = concrete
    device = BaseDevice(sn="TEST", product_name="test", rest=quota, mqtt=publisher)
    await device._publish({"params": {"enabled": False}})  # pyright: ignore[reportPrivateUsage]
    assert concrete.sent[0][0] == "/open/test/TEST/set"
    assert concrete.sent[0][1]["params"] == {"enabled": False}
    concrete.connected = False
    with pytest.raises(EcoFlowConnectionError):
        await device._publish({})  # pyright: ignore[reportPrivateUsage]
    assert len(concrete.sent) == 1
    assert not quota.requests
