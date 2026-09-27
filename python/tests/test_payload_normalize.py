"""Tests for public-API MQTT payload normalisation (envelope → REST layout)."""

from unittest.mock import MagicMock

from ecoflow.devices.battery import BatteryDevice
from ecoflow.devices.plug import SmartPlugDevice
from ecoflow.devices.stream_ultra import StreamUltraDevice
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from ecoflow.transport.payload import normalize_quota_payload


def test_flat_payload_passes_through() -> None:
    assert normalize_quota_payload({"soc": 85}) == {"soc": 85}


def test_params_envelope_is_unwrapped_without_prefix() -> None:
    raw = {"id": 1, "version": "1.0", "params": {"bmsBattSoc": 47.0}}
    assert normalize_quota_payload(raw) == {"bmsBattSoc": 47.0}


def test_cmdfunc_cmdid_envelope_gets_rest_prefix() -> None:
    raw = {"cmdFunc": 2, "cmdId": 1, "param": {"watts": 2640, "switchSta": True}}
    assert normalize_quota_payload(raw) == {"2_1.watts": 2640, "2_1.switchSta": True}


def test_typecode_envelope_gets_module_prefix() -> None:
    raw = {"typeCode": "pdStatus", "params": {"soc": 80}}
    assert normalize_quota_payload(raw) == {"pd.soc": 80}
    raw = {"typeCode": "bmsStatus", "params": {"soc": 79}}
    assert normalize_quota_payload(raw) == {"bms_bmsStatus.soc": 79}


def _transport() -> MqttTransport:
    creds = MqttCredentials(
        url="h",
        port=8883,
        protocol="mqtts",
        username="u",
        password="p",
        client_id="c",
        user_id="acct",
    )
    return MqttTransport(creds)


async def test_stream_push_populates_status_end_to_end() -> None:
    dev = StreamUltraDevice(
        sn="BK11TESTSN000001", product_name="STREAM Ultra", rest=MagicMock()
    )
    t = _transport()
    t.on_message(dev.sn, dev._handle_message)  # pyright: ignore[reportPrivateUsage]
    await t.dispatch_message(
        f"/open/acct/{dev.sn}/quota", {"params": {"bmsBattSoc": 47.0}}
    )
    assert dev.status is not None
    assert dev.status.batt_soc == 47.0


async def test_plug_push_populates_data_end_to_end() -> None:
    dev = SmartPlugDevice(sn="HW52TEST", product_name="Smart Plug", rest=MagicMock())
    t = _transport()
    t.on_message(dev.sn, dev._handle_message)  # pyright: ignore[reportPrivateUsage]
    await t.dispatch_message(
        f"/open/acct/{dev.sn}/quota",
        {"cmdFunc": 2, "cmdId": 1, "param": {"watts": 2640, "switchSta": True}},
    )
    assert dev.data is not None
    assert dev.data.is_on is True
    assert dev.data.power_watts == 264.0


async def test_delta2_pushes_accumulate_into_battery_status() -> None:
    dev = BatteryDevice(sn="R331TEST", product_name="DELTA 2", rest=MagicMock())
    t = _transport()
    t.on_message(dev.sn, dev._handle_message)  # pyright: ignore[reportPrivateUsage]
    topic = f"/open/acct/{dev.sn}/quota"
    await t.dispatch_message(topic, {"typeCode": "pdStatus", "params": {"soc": 80}})
    await t.dispatch_message(
        topic, {"typeCode": "invStatus", "params": {"outputWatts": 150}}
    )
    await t.dispatch_message(topic, {"typeCode": "bmsStatus", "params": {"soc": 79}})
    await t.dispatch_message(
        topic, {"typeCode": "emsStatus", "params": {"f32LcdShowSoc": 80}}
    )
    assert dev.status is not None
    assert dev.status.soc == 80
    assert dev.status.ac_output_watts == 150
    assert [m.soc for m in dev.status.bms_modules] == [79]


def test_battery_status_parses_flat_rest_quota_keys() -> None:
    from ecoflow.models.battery import BatteryStatus

    s = BatteryStatus.from_mqtt_payload(
        "R331TEST",
        {
            "pd.soc": 64,
            "inv.cfgAcEnabled": 1,
            "bms_bmsStatus.soc": 63,
            "mppt.inWatts": 90,
        },
    )
    assert s.soc == 64
    assert s.ac_output_enabled is True
    assert s.mppt_input_watts == 90
    assert [m.soc for m in s.bms_modules] == [63]
