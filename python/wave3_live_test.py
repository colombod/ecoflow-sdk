import asyncio
import os
import sys

sys.path.insert(0, "src")
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("tests/.env"))


async def main() -> None:
    from ecoflow.private import Wave3Connection

    email = os.environ["ECOFLOW_EMAIL"]
    password = os.environ["ECOFLOW_PASSWORD"]
    sn = os.environ.get("ECOFLOW_WAVE3_SN", "AC71XXXXXXXXXXXX")

    print(f"Connecting to Wave 3: {sn} via private API")

    async with Wave3Connection(
        email=email, password=password, device_sns=[sn]
    ) as wave3:
        device = wave3.devices[sn]
        print("MQTT connected. Waiting 45s for device heartbeat...")

        # Poll every 5s
        for i in range(9):
            await asyncio.sleep(5)
            if device.status is not None:
                s = device.status
                print(f"\n=== WAVE 3 STATUS RECEIVED (after {(i + 1) * 5}s) ===")
                print(f"  is_on:              {s.is_on}")
                print(f"  mode:               {s.mode.name}")
                print(f"  battery_soc:        {s.battery_soc:.1f}%")
                print(f"  system_soc:         {s.system_soc:.1f}%")
                print(f"  ambient_temp:       {s.ambient_temp:.1f}°C")
                print(f"  supply_air_temp:    {s.supply_air_temp:.1f}°C")
                print(f"  target_temp:        {s.target_temp:.1f}°C")
                print(
                    f"  airflow_speed:      {s.airflow_speed} (fan_level={s.fan_level})"
                )
                print(f"  submode:            {s.submode}")
                print(f"  ambient_humidity:   {s.ambient_humidity:.1f}%")
                print(f"  water_level:        {s.water_level}%")
                print(f"  input_power:        {s.input_power_watts:.1f}W")
                print(f"  output_power:       {s.output_power_watts:.1f}W")
                print(f"  ac_power:           {s.ac_power_watts:.1f}W")
                print(f"  pv_power:           {s.pv_power_watts:.1f}W")
                print(f"  discharge_time:     {s.discharge_time_min} min")
                print(f"  charge_time:        {s.charge_time_min} min")
                print(f"  condenser_temp:     {s.condenser_temp:.1f}°C")
                print(f"  outdoor_temp:       {s.outdoor_temp:.1f}°C")
                break
        else:
            print("No status received in 45s. Printing raw MQTT topic info.")


asyncio.run(main())
