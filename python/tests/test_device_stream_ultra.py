"""Tests for StreamUltraDevice and StreamAcProDevice abstractions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_QUOTA_PAYLOAD = {
    "cmsBattSoc": 13.0,
    "powGetSysGrid": 1112.0,
    "powGetSysLoad": 1112.0,
    "powGetPvSum": 0.0,
    "cmsMaxChgSoc": 95,
    "cmsMinDsgSoc": 10,
    "feedGridMode": 2,
    "gridConnectionPower": 0.0,
    "relay2Onoff": False,
    "relay3Onoff": False,
    "powGetBpCms": 0.0,
    "backupReverseSoc": 13,
}


def make_stream_ultra(product_name: str = "STREAM Ultra"):  # type: ignore[return]
    from ecoflow.devices.stream_ultra import StreamUltraDevice

    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value=_QUOTA_PAYLOAD)
    return StreamUltraDevice(
        sn="BK11ZK1B2H5S1478", product_name=product_name, rest=rest
    )


@pytest.mark.asyncio
async def test_stream_ultra_refresh_returns_status() -> None:
    """refresh() returns a StreamUltraStatus with the expected batt_soc."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    device = make_stream_ultra()
    status = await device.refresh()
    assert isinstance(status, StreamUltraStatus)
    assert status.batt_soc == pytest.approx(13.0)  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.asyncio
async def test_stream_ultra_refresh_sets_product_name() -> None:
    """refresh() attaches product_name to the returned status."""
    device = make_stream_ultra(product_name="STREAM Ultra")
    status = await device.refresh()
    assert status.product_name == "STREAM Ultra"


@pytest.mark.asyncio
async def test_stream_ultra_refresh_stores_status() -> None:
    """refresh() stores status on device.status."""
    device = make_stream_ultra()
    status = await device.refresh()
    assert device.status is status


@pytest.mark.asyncio
async def test_stream_ultra_set_charge_limit_valid() -> None:
    """set_charge_limit(soc_pct=80) publishes cmsMaxChgSoc."""
    device = make_stream_ultra()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_pub:
        await device.set_charge_limit(soc_pct=80)
    mock_pub.assert_called_once_with({"cmsMaxChgSoc": 80})


@pytest.mark.asyncio
async def test_stream_ultra_set_charge_limit_rejects_below_50() -> None:
    """set_charge_limit() raises ValueError for soc_pct < 50."""
    device = make_stream_ultra()
    with pytest.raises(ValueError):
        await device.set_charge_limit(soc_pct=49)


@pytest.mark.asyncio
async def test_stream_ultra_set_charge_limit_rejects_above_100() -> None:
    """set_charge_limit() raises ValueError for soc_pct > 100."""
    device = make_stream_ultra()
    with pytest.raises(ValueError):
        await device.set_charge_limit(soc_pct=101)


@pytest.mark.asyncio
async def test_stream_ultra_set_discharge_limit_valid() -> None:
    """set_discharge_limit(soc_pct=20) publishes cmsMinDsgSoc."""
    device = make_stream_ultra()
    with patch.object(device, "_publish", new_callable=AsyncMock) as mock_pub:
        await device.set_discharge_limit(soc_pct=20)
    mock_pub.assert_called_once_with({"cmsMinDsgSoc": 20})


@pytest.mark.asyncio
async def test_stream_ultra_set_discharge_limit_rejects_above_30() -> None:
    """set_discharge_limit() raises ValueError for soc_pct > 30."""
    device = make_stream_ultra()
    with pytest.raises(ValueError):
        await device.set_discharge_limit(soc_pct=31)


@pytest.mark.asyncio
async def test_stream_ultra_set_discharge_limit_rejects_below_0() -> None:
    """set_discharge_limit() raises ValueError for soc_pct < 0."""
    device = make_stream_ultra()
    with pytest.raises(ValueError):
        await device.set_discharge_limit(soc_pct=-1)


def test_stream_ultra_handle_message_updates_status() -> None:
    """_handle_message() updates status from the MQTT payload."""
    from ecoflow.models.stream_ultra import StreamUltraStatus

    device = make_stream_ultra()
    device._handle_message("BK11ZK1B2H5S1478", _QUOTA_PAYLOAD)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(device.status, StreamUltraStatus)
    assert device.status.batt_soc == pytest.approx(13.0)  # pyright: ignore[reportUnknownMemberType]


def test_stream_ultra_accumulates_mqtt_chunks() -> None:
    """MQTT data arrives in chunks; status must merge all chunks not just last."""
    from ecoflow.devices.stream_ultra import StreamUltraDevice

    rest = MagicMock()
    device = StreamUltraDevice(sn="BK11TEST", product_name="STREAM Ultra", rest=rest)

    # Chunk 1: grid power only — no SOC fields
    device._handle_message(  # pyright: ignore[reportPrivateUsage]
        "BK11TEST", {"powGetSysGrid": 1200.0, "powGetSysLoad": 500.0}
    )
    assert device.status is not None
    assert device.status.grid_power_watts == pytest.approx(1200.0)  # pyright: ignore[reportUnknownMemberType]
    assert device.status.batt_soc == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]  # SOC not arrived yet

    # Chunk 2: battery SOC only — grid power not repeated
    device._handle_message("BK11TEST", {"bmsBattSoc": 47.0, "cascadeSysSoc": 44})  # pyright: ignore[reportPrivateUsage]
    assert device.status is not None
    # Grid power MUST still be 1200W (preserved from chunk 1, not reset to 0)
    assert device.status.grid_power_watts == pytest.approx(1200.0)  # pyright: ignore[reportUnknownMemberType]
    assert device.status.batt_soc == pytest.approx(47.0)  # pyright: ignore[reportUnknownMemberType]  # populated from chunk 2


def test_stream_ac_pro_is_stream_ultra_subclass() -> None:
    """StreamAcProDevice is a subclass of StreamUltraDevice."""
    from ecoflow.devices.stream_ac_pro import StreamAcProDevice
    from ecoflow.devices.stream_ultra import StreamUltraDevice

    assert issubclass(StreamAcProDevice, StreamUltraDevice)


@pytest.mark.asyncio
async def test_stream_ac_pro_refresh_returns_status() -> None:
    """StreamAcProDevice.refresh() returns StreamUltraStatus (same payload format)."""
    from ecoflow.devices.stream_ac_pro import StreamAcProDevice
    from ecoflow.models.stream_ultra import StreamUltraStatus

    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value=_QUOTA_PAYLOAD)
    device = StreamAcProDevice(
        sn="BK31ZK1A4H4R0224", product_name="STREAM AC Pro", rest=rest
    )
    status = await device.refresh()
    assert isinstance(status, StreamUltraStatus)
    assert status.batt_soc == pytest.approx(13.0)  # pyright: ignore[reportUnknownMemberType]
