"""Raw MQTT diagnostic — uses the EXACT same auth and topic as Wave3Connection.
Prints every byte that arrives on the subscription topic.
"""

import asyncio, os, sys, ssl, uuid

sys.path.insert(0, "src")
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("tests/.env"))


async def main():
    from ecoflow.private.auth import login
    from ecoflow.private.proto.decoder import decode
    import aiomqtt

    email = os.environ["ECOFLOW_EMAIL"]
    password = os.environ["ECOFLOW_PASSWORD"]
    sn = os.environ.get("ECOFLOW_WAVE3_SN", "AC71ZK1APJ410297")

    print(f"=== RAW MQTT DIAGNOSTIC for {sn} ===")
    print("Step 1: Authenticating...")
    creds = await login(email, password)
    print(f"  certificate_account : {creds.certificate_account}")
    print(f"  user_id             : {creds.user_id}")
    print(f"  cert_password len   : {len(creds.certificate_password)} chars")

    client_id = f"ANDROID_{uuid.uuid4().hex.upper()}_{creds.user_id}"
    topic = f"/app/device/property/{sn}"
    print(f"\nStep 2: Connecting to mqtt.ecoflow.com:8883")
    print(f"  client_id : {client_id}")
    print(f"  topic     : {topic}")

    tls_ctx = ssl.create_default_context()
    async with aiomqtt.Client(
        hostname="mqtt.ecoflow.com",
        port=8883,
        username=creds.certificate_account,
        password=creds.certificate_password,
        identifier=client_id,
        keepalive=60,
        tls_context=tls_ctx,
        timeout=30,
    ) as client:
        await client.subscribe(topic, qos=1)
        print(f"\nStep 3: Subscribed. Listening 60s for any message...\n")

        deadline = asyncio.get_event_loop().time() + 60
        count = 0
        async with asyncio.timeout(60):
            async for msg in client.messages:
                count += 1
                payload = bytes(msg.payload)
                print(f"[MSG #{count}] topic={msg.topic}  len={len(payload)}b")
                print(f"  hex[0:32] : {payload[:32].hex()}")
                # Try protobuf decode
                try:
                    data = decode(payload)
                    if data:
                        print(f"  DECODED   : {data}")
                    else:
                        print(f"  DECODED   : (empty / unrecognised proto)")
                except Exception as e:
                    print(f"  DECODE ERR: {e}")
                if asyncio.get_event_loop().time() > deadline:
                    break

    if count == 0:
        print("NO MESSAGES arrived in 60 seconds.")
        print("\nDiagnosis:")
        print("  - MQTT connected OK (no exception)")
        print("  - Subscription succeeded (no exception)")
        print("  - Device is either offline, or EcoFlow cloud doesn't push")
        print("    unsolicited heartbeats to this topic")
        print("  => The device may need a GET request to trigger a push")


asyncio.run(main())
