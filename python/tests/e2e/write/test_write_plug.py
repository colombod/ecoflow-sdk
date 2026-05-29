"""
⚠️  WRITE TESTS — these alter real device state.
    Will NOT run unless BOTH gates are active:
      ECOFLOW_ENABLE_WRITE_TESTS=true  (in tests/.env)
      --enable-write-tests             (pytest CLI flag)

    These tests turn a real Smart Plug on and off.
    DO NOT run in CI. DO NOT run by mistake.
    Only run when explicitly testing write operations.
"""

import asyncio
import os

import pytest

from ecoflow.client import EcoFlowClient
from ecoflow.devices.plug import SmartPlugDevice


def get_write_client() -> EcoFlowClient:
    return EcoFlowClient(
        access_key=os.environ["ECOFLOW_ACCESS_KEY"],
        secret_key=os.environ["ECOFLOW_SECRET_KEY"],
        region=os.getenv("ECOFLOW_REGION", "EU"),
    )


def get_test_plug(client: EcoFlowClient) -> SmartPlugDevice:
    sn = os.environ.get("ECOFLOW_TEST_DEVICE_SN")
    if not sn:
        pytest.skip("ECOFLOW_TEST_DEVICE_SN not set")
    plug = next((p for p in client.plugs if p.sn == sn), None)
    if plug is None:
        pytest.skip(f"Smart Plug {sn} not found in account")
    return plug


@pytest.mark.write_integration
async def test_plug_turn_on() -> None:
    async with get_write_client() as client:
        plug = get_test_plug(client)
        await plug.turn_on()
        await asyncio.sleep(2)  # allow state to propagate
        status = await plug.refresh()
        assert status.is_on is True


@pytest.mark.write_integration
async def test_plug_turn_off() -> None:
    async with get_write_client() as client:
        plug = get_test_plug(client)
        await plug.turn_off()
        await asyncio.sleep(2)
        status = await plug.refresh()
        assert status.is_on is False


@pytest.mark.write_integration
async def test_plug_toggle_restores_state() -> None:
    """Toggle on → off → on — leaves plug in original state."""
    async with get_write_client() as client:
        plug = get_test_plug(client)
        initial = await plug.refresh()
        await plug.toggle()
        await asyncio.sleep(2)
        mid = await plug.refresh()
        assert mid.is_on != initial.is_on
        await plug.toggle()
        await asyncio.sleep(2)
        final = await plug.refresh()
        assert final.is_on == initial.is_on
