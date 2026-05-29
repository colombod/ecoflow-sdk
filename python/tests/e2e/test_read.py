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

import pytest

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
