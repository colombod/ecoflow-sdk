"""Read-only E2E integration tests — require real EcoFlow credentials.

Run with: uv run pytest -m integration --timeout=60

Credentials loaded from tests/.env:
  ECOFLOW_ACCESS_KEY
  ECOFLOW_SECRET_KEY
  ECOFLOW_REGION           (default: EU)
  ECOFLOW_TEST_DEVICE_SN   (optional — serial of a known device)
"""

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
