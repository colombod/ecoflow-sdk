"""
STREAM write integration tests — relay ON/OFF.

EXPLICIT OPT-IN required (two independent gates):
    1. ECOFLOW_ENABLE_WRITE_TESTS=true  in tests/.env
    2. --enable-write-tests             pytest CLI flag

Example:
    uv run pytest tests/e2e/write/test_stream_relay_commands.py \\
        -m write_integration --enable-write-tests -v -s

WARNING: This test sends real set commands to live STREAM Ultra / STREAM AC Pro
hardware.  It will turn the relay2 outlet ON then OFF.  Do not run accidentally.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


@pytest.mark.write_integration
async def test_stream_relay2_on_off_sequence() -> None:
    """Turn relay2 ON then OFF and verify state changes via REST refresh.

    Timing notes (from live-device characterisation, 2026-06-01):
    - REST /quota/all responds immediately, no MQTT wait needed.
    - 10 s sleep between command and refresh is conservative but reliable;
      the relay state was confirmed changed within that window on BK11.
    - MQTT round-trip for relay commands is typically < 2 s, but REST
      refresh is used here to avoid MQTT subscription complexity in E2E tests.
    """
    from ecoflow.client import EcoFlowClient

    if not os.environ.get("ECOFLOW_ENABLE_WRITE_TESTS"):
        pytest.skip("ECOFLOW_ENABLE_WRITE_TESTS not set")

    access_key = os.environ.get("ECOFLOW_ACCESS_KEY", "")
    secret_key = os.environ.get("ECOFLOW_SECRET_KEY", "")
    region = os.environ.get("ECOFLOW_REGION", "EU")

    if not access_key or not secret_key:
        pytest.skip("ECOFLOW_ACCESS_KEY / ECOFLOW_SECRET_KEY not set in tests/.env")

    async with EcoFlowClient(
        access_key=access_key,
        secret_key=secret_key,
        region=region,
    ) as client:
        target = client.stream_units[0] if client.stream_units else None
        if not target:
            pytest.skip("No STREAM units available in this account")

        # Wait for MQTT connection to stabilise before sending commands.
        await asyncio.sleep(15)

        s0 = await target.refresh()
        initial_state = s0.relay2_on
        print(f"\n[relay2] initial: {initial_state}  (sn={target.sn})")

        # ------------------------------------------------------------------ #
        # Step 1: turn relay2 ON, verify via REST refresh                     #
        # ------------------------------------------------------------------ #
        print(f"[relay2] sending set_relay2(on=True) to {target.sn} ...")
        await target.set_relay2(on=True)
        await asyncio.sleep(10)

        s_on = await target.refresh()
        print(f"[relay2] after ON: relay2_on={s_on.relay2_on}")
        assert s_on.relay2_on is True, (
            f"relay2 ON failed: relay2_on={s_on.relay2_on} on {target.sn}"
        )
        print("[relay2] OK — relay2_on=True confirmed via REST")

        # ------------------------------------------------------------------ #
        # Step 2: turn relay2 OFF, verify via REST refresh                    #
        # ------------------------------------------------------------------ #
        print(f"[relay2] sending set_relay2(on=False) to {target.sn} ...")
        await target.set_relay2(on=False)
        await asyncio.sleep(10)

        s_off = await target.refresh()
        print(f"[relay2] after OFF: relay2_on={s_off.relay2_on}")
        assert s_off.relay2_on is False, (
            f"relay2 OFF failed: relay2_on={s_off.relay2_on} on {target.sn}"
        )
        print("[relay2] OK — relay2_on=False confirmed via REST")

        print(f"\n✅ relay2 ON→OFF sequence confirmed on {target.sn}")
