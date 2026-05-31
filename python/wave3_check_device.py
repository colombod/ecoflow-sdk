"""Check if device SN is visible on this EcoFlow account via REST API."""

import asyncio
import base64
import os
import sys

sys.path.insert(0, "src")
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("tests/.env"))


async def main() -> None:
    import httpx

    email = os.environ["ECOFLOW_EMAIL"]
    password = os.environ["ECOFLOW_PASSWORD"]

    encoded_password = base64.b64encode(password.encode()).decode()
    headers = {"lang": "en_US", "country": "US"}

    async with httpx.AsyncClient(timeout=30) as client:
        # Login
        resp = await client.post(
            "https://api.ecoflow.com/auth/login",
            json={
                "email": email,
                "password": encoded_password,
                "scene": "IOT_APP",
                "userType": "ECOFLOW",
            },
            headers=headers,
        )
        body = resp.json()
        if str(body.get("code", "-1")) != "0":
            print(f"Login failed: {body}")
            return

        token = body["data"]["token"]
        user_id = body["data"]["user"]["userId"]
        print(f"Login OK: userId={user_id}")

        # Get device list
        resp2 = await client.get(
            "https://api.ecoflow.com/iot-service/open/api/device/queryDeviceList",
            headers={**headers, "authorization": f"Bearer {token}"},
        )
        body2 = resp2.json()
        print(f"\nDevice list response code: {body2.get('code')}")
        devices = body2.get("data", [])
        if isinstance(devices, list):
            print(f"Devices on account ({len(devices)} total):")
            for d in devices:
                sn_d = d.get("sn", d.get("deviceSn", "?"))
                name = d.get("deviceName", d.get("productName", "?"))
                online = d.get("online", "?")
                print(f"  SN={sn_d:30s}  name={name:30s}  online={online}")
        else:
            print(f"Unexpected device list format: {body2}")


asyncio.run(main())
