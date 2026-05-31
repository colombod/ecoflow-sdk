"""Subscribe to ALL EcoFlow topics for this user/device to see what arrives."""

import asyncio
import os
import ssl
import sys
import uuid

sys.path.insert(0, "src")
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("tests/.env"))


async def main() -> None:
    import aiomqtt

    from ecoflow.private.auth import login

    email = os.environ["ECOFLOW_EMAIL"]
    password = os.environ["ECOFLOW_PASSWORD"]
    sn = os.environ.get("ECOFLOW_WAVE3_SN", "AC71ZK1APJ410297")

    print("Authenticating...")
    creds = await login(email, password)
    print(f"  user_id={creds.user_id}  cert_account={creds.certificate_account}")

    client_id = f"ANDROID_{uuid.uuid4().hex.upper()}_{creds.user_id}"
    tls_ctx = ssl.create_default_context()

    print(f"\nConnecting with client_id={client_id}")
    try:
        async with aiomqtt.Client(
            hostname="mqtt.ecoflow.com",
            port=8883,
            username=creds.certificate_account,
            password=creds.certificate_password,
            identifier=client_id,
            keepalive=60,
            tls_context=tls_ctx,
            timeout=15,
        ) as client:
            # Try the production topic first
            print(
                f"Subscribing to /app/device/property/{sn}"
                f" and /app/{creds.user_id}/{sn}/#"
            )
            await client.subscribe(f"/app/device/property/{sn}", qos=1)
            await client.subscribe(f"/app/{creds.user_id}/{sn}/#", qos=1)
            print("Subscribed. Waiting 45s for ANY message...\n")

            count = 0
            try:
                async with asyncio.timeout(45):
                    async for msg in client.messages:
                        count += 1
                        payload = bytes(msg.payload)
                        print(
                            f"[MSG #{count}] topic={msg.topic}"
                            f"  len={len(payload)}b"
                            f"  hex={payload[:24].hex()}"
                        )
                        if count >= 5:
                            break
            except TimeoutError:
                pass

            if count == 0:
                print("RESULT: 0 messages in 45s on device-specific topics")
                print("\nTrying # wildcard for 15s to see if ANY traffic exists...")
                await client.subscribe("#", qos=0)
                wc_count = 0
                try:
                    async with asyncio.timeout(15):
                        async for msg in client.messages:
                            wc_count += 1
                            payload = bytes(msg.payload)
                            print(
                                f"  [WILDCARD] topic={msg.topic}  len={len(payload)}b"
                            )
                            if wc_count >= 3:
                                break
                except TimeoutError:
                    pass
                if wc_count == 0:
                    print(
                        "  RESULT: 0 messages on # wildcard"
                        " — broker connects but device is silent"
                    )
                else:
                    print(f"  RESULT: {wc_count} messages on #")
    except Exception as e:
        print(f"MQTT error: {e}")


asyncio.run(main())
