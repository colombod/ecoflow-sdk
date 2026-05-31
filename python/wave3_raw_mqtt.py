"""Diagnostic: show raw MQTT messages so we can see what's arriving vs what's parsed."""

import asyncio, os, sys

sys.path.insert(0, "src")
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("tests/.env"))


async def main():
    import logging

    # Enable INFO so we can see connection messages without debug spam
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    # Silence noisy loggers
    for name in ("aiomqtt", "ecoflow.private.auth"):
        logging.getLogger(name).setLevel(logging.WARNING)

    from ecoflow.private.auth import PrivateCredentials
    from ecoflow.private.connection import PrivateConnection
    import aiomqtt

    email = os.environ["ECOFLOW_EMAIL"]
    password = os.environ["ECOFLOW_PASSWORD"]
    sn = os.environ.get("ECOFLOW_WAVE3_SN", "AC71ZK1APJ410297")

    print(f"=== RAW MQTT DIAGNOSTIC for {sn} ===")
    creds = await PrivateCredentials.login(email=email, password=password)
    print(f"Auth OK — userId={creds.user_id}")

    client_id = f"ANDROID_{creds.user_id}_{sn}"
    topics = [
        f"/open/{creds.user_id}/{sn}/quota",
        f"/open/{creds.user_id}/{sn}/get_reply",
        f"/app/{creds.user_id}/{sn}/thing/property/set_reply",
        f"/app/device/property/{sn}",
        f"/app/{creds.user_id}/{sn}/thing/property/get_reply",
    ]

    print(f"Subscribing to {len(topics)} topics...")
    for t in topics:
        print(f"  {t}")

    async with aiomqtt.Client(
        hostname="mqtt.ecoflow.com",
        port=8883,
        username=creds.user_id,
        password=creds.token,
        identifier=client_id,
        tls_params=aiomqtt.TLSParameters(),
        timeout=30,
    ) as client:
        async with client.messages() as messages:
            for t in topics:
                await client.subscribe(t)
            print(
                "\nMQTT connected + subscribed. Listening 60s for any message on any topic..."
            )
            deadline = asyncio.get_event_loop().time() + 60
            count = 0
            async for msg in messages:
                count += 1
                payload_bytes = bytes(msg.payload)
                payload_preview = payload_bytes[:120]
                print(f"\n[MSG #{count}] topic={msg.topic}")
                print(f"  len={len(payload_bytes)} bytes")
                # Try to show hex of first 32 bytes
                print(f"  hex[0:32]={payload_bytes[:32].hex()}")
                # Try to show as string if printable
                try:
                    text = payload_bytes.decode("utf-8")
                    print(f"  utf8={text[:200]}")
                except Exception:
                    print(f"  (binary payload)")
                if asyncio.get_event_loop().time() > deadline:
                    break
            if count == 0:
                print("\nNO MESSAGES received in 60s.")
                print("Possible causes:")
                print("  1. Device is truly offline / not on WiFi")
                print("  2. Topics are wrong for this firmware version")
                print(
                    "  3. Cloud broker doesn't push unsolicited; need a GET request first"
                )


asyncio.run(main())
