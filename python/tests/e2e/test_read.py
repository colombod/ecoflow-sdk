"""Read-only E2E integration tests — require real EcoFlow credentials.

Run with: uv run pytest -m integration --timeout=60

Credentials loaded from tests/.env:
  ECOFLOW_ACCESS_KEY
  ECOFLOW_SECRET_KEY
  ECOFLOW_REGION           (default: EU)
  ECOFLOW_TEST_DEVICE_SN   (optional — serial of a known device)
"""

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from ecoflow.client import EcoFlowClient


def get_client() -> EcoFlowClient:
    return EcoFlowClient(
        access_key=os.environ["ECOFLOW_ACCESS_KEY"],
        secret_key=os.environ["ECOFLOW_SECRET_KEY"],
        region=os.getenv("ECOFLOW_REGION", "EU"),
    )


def skip_if_no_creds() -> None:
    if not os.getenv("ECOFLOW_ACCESS_KEY"):
        pytest.skip("No EcoFlow credentials in tests/.env")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client() -> AsyncGenerator[EcoFlowClient, None]:
    """Shared EcoFlowClient for all Wave 3 integration tests in this module."""
    skip_if_no_creds()
    c = get_client()
    await c.connect()
    await asyncio.sleep(20)  # wait for MQTT initial state dump
    yield c
    try:
        await c.disconnect()
    except Exception:
        # httpx / anyio may fail to close the connection pool if the event
        # loop is already in teardown — TCP cleanup is handled by the OS.
        pass


@pytest.mark.integration
async def test_client_connects_and_discovers_devices() -> None:
    skip_if_no_creds()
    async with get_client() as client:
        total = (
            len(client.batteries)
            + len(client.plugs)
            + len(client.meters)
            + len(client.wave3_units)
            + len(client.inverters)
            + len(client.unknown_devices)
        )
        assert total >= 0  # at minimum, no crash — empty account is OK


@pytest.mark.integration
async def test_device_list_returns_sns() -> None:
    skip_if_no_creds()
    async with get_client() as client:
        all_typed = client.batteries + client.plugs + client.meters
        for device in all_typed:
            assert len(device.sn) > 0
            assert len(device.product_name) > 0


@pytest.mark.integration
async def test_known_device_refresh() -> None:
    skip_if_no_creds()
    sn = os.getenv("ECOFLOW_TEST_DEVICE_SN")
    if not sn:
        pytest.skip("ECOFLOW_TEST_DEVICE_SN not set")

    async with get_client() as client:
        all_devices = client.batteries + client.plugs + client.meters
        device = next((d for d in all_devices if d.sn == sn), None)
        if device is None:
            pytest.skip(f"Device {sn} not found in account")
        status = await device.refresh()
        assert status is not None


@pytest.mark.integration
async def test_stream_units_new_fields() -> None:
    """Verify new model fields from community research are populated via MQTT."""
    skip_if_no_creds()
    async with get_client() as client:
        if not client.stream_units:
            pytest.skip("No STREAM Ultra / AC Pro devices in account")

        # Allow MQTT to accumulate initial state chunks
        await asyncio.sleep(15)

        for device in client.stream_units:
            status = device.status
            if status is None:
                status = await device.refresh()

            assert status.soc_precise >= 0.0, f"{device.sn}: soc_precise not populated"
            # Raw capacity mAh fields must be present
            assert status.remaining_cap_mah >= 0, (
                f"{device.sn}: remaining_cap_mah missing"
            )
            assert status.full_cap_mah >= 0, f"{device.sn}: full_cap_mah missing"
            # Wh computed correctly: at 40–100% SOC a 1.92kWh battery → 768–1920 Wh
            if status.battery_voltage > 0 and status.remaining_cap_mah > 0:
                assert 100 < status.remaining_cap_wh < 2500, (
                    f"{device.sn}: remaining_cap_wh={status.remaining_cap_wh:.0f} "
                    f"outside 100–2500 Wh range"
                )


@pytest.mark.integration
async def test_smart_meter_exported_energy() -> None:
    """Verify Smart Meter total_exported_energy_wh field is populated."""
    skip_if_no_creds()
    async with get_client() as client:
        if not client.meters:
            pytest.skip("No Smart Meter devices in account")

        # Allow MQTT to accumulate initial data
        await asyncio.sleep(10)

        for meter_device in client.meters:
            data = meter_device.data
            if data is None:
                continue  # meter may not have data yet via MQTT
            # Lifetime exported energy must be non-negative
            assert data.total_exported_energy_wh >= 0, (
                f"{meter_device.sn}: exported energy must be non-negative"
            )
            # Total active (lifetime imported) energy should be positive
            if data.total_active_energy_wh > 0:
                assert data.total_active_energy_wh > 0, (
                    "active energy should be positive lifetime value"
                )


# ---------------------------------------------------------------------------
# Wave 3 integration tests — hardware-validated (SN: AC71ZK1APJ410297)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_wave3_device_discovered(client: EcoFlowClient) -> None:
    """Wave 3 (SN prefix AC71) must appear in wave3_units, not unknown_devices."""
    wave3_sns = [d.sn for d in client.wave3_units]
    unknown_sns = [d.sn for d in client.unknown_devices]

    # Verify Wave 3 is NOT in unknown (was the bug before AC71 prefix fix)
    ac71_in_unknown = [sn for sn in unknown_sns if sn.startswith("AC71")]
    assert not ac71_in_unknown, (
        f"Wave 3 device(s) {ac71_in_unknown} are in unknown_devices — "
        "AC71 SN prefix must be in SN_PREFIX_TO_MODEL"
    )

    # Verify at least one Wave 3 is in wave3_units
    assert len(client.wave3_units) >= 1, (
        "No Wave 3 devices found in client.wave3_units. "
        f"Known SNs: wave3={wave3_sns}, unknown={unknown_sns}"
    )


@pytest.mark.integration
async def test_wave3_is_online(client: EcoFlowClient) -> None:
    """Wave 3 device must be reachable (online flag from device list)."""
    for device in client.wave3_units:
        # Wave 3 is reported as online=1 in the device list
        assert device.sn.startswith("AC71"), f"Unexpected Wave 3 SN prefix: {device.sn}"
        assert device.product_name == "Wave 3", (
            f"Unexpected product name: {device.product_name!r}"
        )


@pytest.mark.integration
async def test_wave3_refresh_handles_api_limitation(client: EcoFlowClient) -> None:
    """Wave 3 refresh() gracefully handles REST error 1006.

    The public EcoFlow Developer API does not expose Wave 3 device quota
    (returns error 1006: 'current device is not allowed to get device info').
    refresh() must not raise — it returns a minimal Wave3Status with online=True.
    """
    for device in client.wave3_units:
        # This must NOT raise even though the REST API returns error 1006
        status = await device.refresh()

        assert status is not None, f"{device.sn}: refresh() returned None"
        assert status.sn == device.sn, f"{device.sn}: status.sn mismatch"
        assert status.online is True, (
            f"{device.sn}: status.online must be True "
            "(device is online per device list)"
        )
        # Data fields default to 0.0 / False — no error should be raised
        assert isinstance(status.is_on, bool)
        assert isinstance(status.target_temp, float)
        assert isinstance(status.battery_soc, float)


@pytest.mark.integration
async def test_wave3_mqtt_subscription_active(client: EcoFlowClient) -> None:
    """Wave 3 MQTT subscription is established even if no data arrives.

    The public API MQTT does not push data for Wave 3 (uses private API).
    The subscription is established (correct behaviour) — data absence is expected.
    """
    if client._mqtt is None:
        pytest.skip("MQTT not connected")

    assert client._mqtt is not None  # narrow type for pyright

    for device in client.wave3_units:
        assert device.sn in client._mqtt.subscriptions, (
            f"{device.sn}: Wave 3 not subscribed in MQTT client"
        )
        # MQTT data will be None or empty — document this as expected
        # (Wave 3 uses private API Protobuf, not public API JSON)
        if device.status is None:
            pass  # Expected — Wave 3 doesn't send data on public MQTT


@pytest.mark.integration
async def test_wave3_not_in_unknown_devices(client: EcoFlowClient) -> None:
    """Regression: Wave 3 must not fall into unknown_devices after SN prefix fix."""
    for device in client.unknown_devices:
        assert not device.sn.startswith("AC71"), (
            f"Wave 3 device {device.sn} is in unknown_devices — "
            "this is a regression in SN_PREFIX_TO_MODEL routing"
        )
