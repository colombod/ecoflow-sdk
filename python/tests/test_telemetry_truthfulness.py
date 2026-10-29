"""Offline regressions for missing readings and partial-update freshness."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoflow.devices.meter import SmartMeterDevice
from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.devices.stream_ultra import StreamUltraDevice
from ecoflow.exceptions import EcoFlowDataUnavailableError
from ecoflow.models.plug import SmartPlugData


def test_missing_plug_energy_is_unknown_but_zero_is_real() -> None:
    assert SmartPlugData.from_quota_payload("HW52TEST", {}).daily_energy_wh is None
    assert SmartPlugData.from_mqtt_payload("HW52TEST", {}).daily_energy_wh is None
    assert (
        SmartPlugData.from_mqtt_payload("HW52TEST", {"watth5": 0}).daily_energy_wh == 0
    )
    assert (
        SmartPlugData.from_mqtt_payload("HW52TEST", {"watth5": 456}).daily_energy_wh
        == 45.6
    )


@pytest.mark.parametrize("cached", [False, True])
async def test_empty_meter_rest_cannot_replace_readings(cached: bool) -> None:
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={})
    meter = SmartMeterDevice(sn="BK21TEST", product_name="meter", rest=rest)
    if cached:
        meter._handle_message("BK21TEST", {"powGetSysGrid": 0})  # pyright: ignore[reportPrivateUsage]
    previous = meter.data
    with pytest.raises(EcoFlowDataUnavailableError, match="MQTT"):
        await meter.refresh()
    assert meter.data is previous


@pytest.mark.parametrize(
    "device_type", [SmartMeterDevice, SmartPlugDevice, StreamUltraDevice]
)
def test_partial_updates_preserve_field_receive_times(
    device_type: type[SmartMeterDevice | SmartPlugDevice | StreamUltraDevice],
) -> None:
    device = device_type(sn="TEST", product_name="test", rest=MagicMock())
    key = "2_1.watts" if device_type is SmartPlugDevice else "powGetSysGrid"
    first = datetime(2026, 10, 29, tzinfo=UTC)
    later = first + timedelta(minutes=10)
    with patch("ecoflow.devices.base.datetime") as clock:
        clock.now.return_value = first
        device._handle_message("TEST", {key: 0})  # pyright: ignore[reportPrivateUsage]
        clock.now.return_value = later
        device._handle_message("TEST", {"temp": 22})  # pyright: ignore[reportPrivateUsage]
    times = device.field_received_at
    assert times[key] == first
    assert times["temp"] == later
    assert "watth5" not in times
    times.clear()
    assert device.field_received_at[key] == first


async def test_stream_rest_does_not_rejuvenate_pack_fields() -> None:
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={"cmsBattSoc": 0})
    stream = StreamUltraDevice(sn="BK31TEST", product_name="stream", rest=rest)
    stream._handle_message("BK31TEST", {"soc": 13, "vol": 50000})  # pyright: ignore[reportPrivateUsage]
    received = stream.field_received_at["soc"]
    await stream.refresh()
    assert stream.status is not None
    assert stream.status.batt_soc == 13
    assert stream.field_received_at["soc"] == received
    assert "cmsBattSoc" in stream.field_received_at


def test_nested_meter_energy_chunks_preserve_other_readings() -> None:
    meter = SmartMeterDevice(sn="BK21TEST", product_name="meter", rest=MagicMock())
    meter._handle_message("BK21TEST", {"gridConnectionDataRecord": {"todayActive": 42}})  # pyright: ignore[reportPrivateUsage]
    received = meter.field_received_at["gridConnectionDataRecord.todayActive"]
    meter._handle_message(  # pyright: ignore[reportPrivateUsage]
        "BK21TEST", {"gridConnectionDataRecord": {"totalActiveEnergy": 500}}
    )  # pyright: ignore[reportPrivateUsage]
    assert meter.data is not None
    assert meter.data.today_active_energy_wh == 42
    assert meter.field_received_at["gridConnectionDataRecord.todayActive"] == received


@pytest.mark.parametrize(
    "device_type", [SmartMeterDevice, SmartPlugDevice, StreamUltraDevice]
)
def test_empty_mqtt_does_not_create_a_reading(
    device_type: type[SmartMeterDevice | SmartPlugDevice | StreamUltraDevice],
) -> None:
    device = device_type(sn="TEST", product_name="test", rest=MagicMock())
    device._handle_message("TEST", {})  # pyright: ignore[reportPrivateUsage]
    assert getattr(device, "data", None) is None
    assert getattr(device, "status", None) is None
    assert not device.field_received_at


def test_ignored_plug_voltage_does_not_refresh_receipt_time() -> None:
    plug = SmartPlugDevice(sn="HW52TEST", product_name="plug", rest=MagicMock())
    plug._handle_message("HW52TEST", {"2_1.volt": 230})  # pyright: ignore[reportPrivateUsage]
    previous = plug.data
    received = plug.field_received_at["2_1.volt"]
    plug._handle_message("HW52TEST", {"2_1.volt": 0})  # pyright: ignore[reportPrivateUsage]
    assert plug.data is previous
    assert plug.field_received_at["2_1.volt"] == received


async def test_plug_rest_refresh_metadata_matches_new_snapshot() -> None:
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={"2_1.watts": 0, "2_1.volt": 230})
    plug = SmartPlugDevice(sn="HW52TEST", product_name="plug", rest=rest)
    plug._handle_message("HW52TEST", {"watth5": 456})  # pyright: ignore[reportPrivateUsage]
    data = await plug.refresh()
    assert data.daily_energy_wh is None
    assert data.power_watts == 0
    assert set(plug.field_received_at) == {"2_1.watts", "2_1.volt"}


@pytest.mark.parametrize("legacy", [False, True])
async def test_plug_mqtt_updates_after_rest_refresh(legacy: bool) -> None:
    """REST must not select the wrong parser for the next MQTT callback."""
    from ecoflow.transport.mqtt import MqttCredentials, MqttTransport

    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={"2_1.watts": 100, "2_1.switchSta": False})
    plug = SmartPlugDevice(sn="HW52TEST", product_name="plug", rest=rest)
    transport = MqttTransport(
        MqttCredentials("offline.invalid", 8883, "mqtts", "u", "p", "c", "test")
    )
    transport.on_message(plug.sn, plug._handle_message)  # pyright: ignore[reportPrivateUsage]
    await plug.refresh()
    payload = (
        {"plug_heartbeat": {"watts": 500, "plugState": 1}}
        if legacy
        else {"cmdFunc": 2, "cmdId": 1, "params": {"watts": 500, "switchSta": True}}
    )
    await transport.dispatch_message(f"/open/test/{plug.sn}/quota", payload)
    assert plug.data is not None
    assert plug.data.power_watts == 50
    assert plug.data.is_on is True
    key = "plug_heartbeat.watts" if legacy else "2_1.watts"
    assert key in plug.field_received_at


@pytest.mark.parametrize("legacy", [False, True])
async def test_plug_rest_does_not_erase_partial_mqtt_state(legacy: bool) -> None:
    """Retained MQTT values and times survive a REST view and transport reset."""
    from ecoflow.transport.mqtt import MqttCredentials, MqttTransport

    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value={"2_1.watts": 100, "2_1.switchSta": False})
    plug = SmartPlugDevice(sn="HW52TEST", product_name="plug", rest=rest)
    transport = MqttTransport(
        MqttCredentials("offline.invalid", 8883, "mqtts", "u", "p", "c", "test")
    )
    transport.on_message(plug.sn, plug._handle_message)  # pyright: ignore[reportPrivateUsage]
    topic = f"/open/test/{plug.sn}/quota"
    payload = (
        {"plug_heartbeat": {"watts": 500, "plugState": 1}}
        if legacy
        else {"cmdFunc": 2, "cmdId": 1, "params": {"watts": 500, "switchSta": True}}
    )
    await transport.dispatch_message(topic, payload)
    key = "plug_heartbeat.watts" if legacy else "2_1.watts"
    received = plug.field_received_at[key]
    await plug.refresh()
    assert "plug_heartbeat.watts" not in plug.field_received_at
    await transport.disconnect()  # no socket was opened; exercise reset only
    partial = (
        {"plug_heartbeat": {"curr": 0}}
        if legacy
        else {"cmdFunc": 2, "cmdId": 1, "params": {"current": 0}}
    )
    await transport.dispatch_message(topic, partial)
    assert plug.data is not None
    assert plug.data.power_watts == 50
    assert plug.data.is_on is True
    assert plug.data.current == 0
    assert plug.field_received_at[key] == received


@pytest.mark.parametrize("rest_first", [False, True])
async def test_stream_strategy_value_matches_its_receipt_time(rest_first: bool) -> None:
    """Recorded REST flat keys and MQTT nested keys describe the same modes."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(
        return_value={"energyStrategyOperateMode.operateSelfPoweredOpen": False}
    )
    stream = StreamUltraDevice(sn="BK11TEST", product_name="stream", rest=rest)
    nested = {"energyStrategyOperateMode": {"operateSelfPoweredOpen": True}}
    if rest_first:
        await stream.refresh()
        stream._handle_message(stream.sn, nested)  # pyright: ignore[reportPrivateUsage]
    else:
        stream._handle_message(stream.sn, nested)  # pyright: ignore[reportPrivateUsage]
        await stream.refresh()
    assert stream.status is not None
    assert stream.status.self_powered_mode is rest_first
    assert (
        "energyStrategyOperateMode.operateSelfPoweredOpen" in stream.field_received_at
    )


@pytest.mark.parametrize("flat", [False, True, None])
def test_stream_strategy_same_payload_precedence_and_no_input_alias(
    flat: bool | None,
) -> None:
    from ecoflow.models.stream_ultra import StreamUltraStatus

    stream = StreamUltraDevice(sn="BK11TEST", product_name="stream", rest=MagicMock())
    modes = {"operateSelfPoweredOpen": True}
    payload = {
        "energyStrategyOperateMode": modes,
        "energyStrategyOperateMode.operateSelfPoweredOpen": flat,
    }
    expected = StreamUltraStatus.from_quota_payload(
        stream.sn, payload
    ).self_powered_mode
    stream._handle_message(stream.sn, payload)  # pyright: ignore[reportPrivateUsage]
    modes["operateSelfPoweredOpen"] = False
    stream._handle_message(stream.sn, {"temp": 20})  # pyright: ignore[reportPrivateUsage]
    assert stream.status is not None
    assert stream.status.self_powered_mode is expected
