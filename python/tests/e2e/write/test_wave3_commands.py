"""
WRITE TESTS -- these alter real device state.
    Will NOT run unless BOTH gates are active:
      ECOFLOW_ENABLE_WRITE_TESTS=true  (in tests/.env)
      --enable-write-tests             (pytest CLI flag)

    These tests send commands to a real Wave 3 AC unit:
      turn_on -> set_mode -> set_temperature -> set_fan_speed -> turn_off.
    DO NOT run in CI. DO NOT run by mistake.
    Only run when explicitly testing Wave 3 write operations.
"""

import asyncio

import pytest

from ecoflow.models.wave3 import Wave3Mode, Wave3Status
from ecoflow.private.connection import Wave3Connection
from tests.conftest import get_private_email, get_private_password, get_wave3_sn


@pytest.mark.write_integration
async def test_wave3_write_commands_sequence() -> None:
    """Sequential smoke test: on -> mode -> temp -> fan -> off."""
    email = get_private_email()
    password = get_private_password()
    sn = get_wave3_sn()

    async with Wave3Connection(
        email=email,
        password=password,
        device_sns=[sn],
    ) as conn:
        device = conn.devices[sn]

        # ------------------------------------------------------------------ #
        # Step 1: turn_on -> wait up to 20 s (40 x 0.5s) for is_on == True  #
        # ------------------------------------------------------------------ #
        print(f"\n[write] turn_on({sn}) ...")
        await conn.turn_on(sn)
        status: Wave3Status | None = None
        for _ in range(40):
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.is_on:
                status = device.status
                break
        assert status is not None, (
            f"Device {sn} did not turn on within 20 s (no status received)"
        )
        assert status.is_on, f"Device {sn} not on (is_on={status.is_on!r})"
        print("[write] OK is_on=True")

        # ------------------------------------------------------------------ #
        # Step 2: set_mode(COOLING) -> wait up to 5 s (10 x 0.5s)           #
        # ------------------------------------------------------------------ #
        print(f"[write] set_mode({sn}, Wave3Mode.COOLING) ...")
        await conn.set_mode(sn, Wave3Mode.COOLING)
        mode_status: Wave3Status | None = None
        for _ in range(10):
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.mode == Wave3Mode.COOLING:
                mode_status = device.status
                break
        assert mode_status is not None, (
            f"Device {sn} mode did not reach COOLING within 5 s (no status received)"
        )
        assert mode_status.mode == Wave3Mode.COOLING, (
            f"Device {sn} mode not COOLING (mode={mode_status.mode!r})"
        )
        print("[write] OK mode=Wave3Mode.COOLING")

        # ------------------------------------------------------------------ #
        # Step 3: set_temperature(25.0) -> wait up to 5 s (10 x 0.5s)       #
        # ------------------------------------------------------------------ #
        print(f"[write] set_temperature({sn}, 25.0) ...")
        await conn.set_temperature(sn, 25.0)
        temp_status: Wave3Status | None = None
        for _ in range(10):
            await asyncio.sleep(0.5)
            if (
                device.status is not None
                and abs(device.status.target_temp - 25.0) < 0.5
            ):
                temp_status = device.status
                break
        assert temp_status is not None, (
            f"Device {sn} target_temp did not reach 25.0 within 5 s "
            "(no status received)"
        )
        assert abs(temp_status.target_temp - 25.0) < 0.5, (
            f"Device {sn} target_temp not near 25.0 "
            f"(target_temp={temp_status.target_temp!r})"
        )
        print("[write] OK target_temp~=25.0")

        # ------------------------------------------------------------------ #
        # Step 4: set_fan_speed(3) -> wait up to 5 s for fan_level == 3      #
        # ------------------------------------------------------------------ #
        print(f"[write] set_fan_speed({sn}, 3) ...")
        await conn.set_fan_speed(sn, 3)
        fan_status: Wave3Status | None = None
        for _ in range(10):
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.fan_level == 3:
                fan_status = device.status
                break
        assert fan_status is not None, (
            f"Device {sn} fan_level did not reach 3 within 5 s (no status received)"
        )
        assert fan_status.fan_level == 3, (
            f"Device {sn} fan_level not 3 (fan_level={fan_status.fan_level!r})"
        )
        print("[write] OK fan_level=3")

        # ------------------------------------------------------------------ #
        # Step 5: turn_off -> wait up to 10 s (20 x 0.5s) for is_on == False #
        # ------------------------------------------------------------------ #
        print(f"[write] turn_off({sn}) ...")
        await conn.turn_off(sn)
        off_status: Wave3Status | None = None
        for _ in range(20):
            await asyncio.sleep(0.5)
            if device.status is not None and not device.status.is_on:
                off_status = device.status
                break
        assert off_status is not None, (
            f"Device {sn} did not turn off within 10 s (no status received)"
        )
        assert not off_status.is_on, (
            f"Device {sn} still on (is_on={off_status.is_on!r})"
        )
        print("[write] OK is_on=False -- sequence complete")
