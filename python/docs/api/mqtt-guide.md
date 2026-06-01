# MQTT Guide — ecoflow-python

This guide covers both MQTT systems used by EcoFlow devices, the protocol details, the
quota limits that will bite you, and the lessons learned the hard way during library development.

> **If you skip to the code first:** Read the quota section. You can exhaust the daily connection
> budget in minutes without realising it.

---

## Overview — Two Separate MQTT Systems

EcoFlow runs two completely different MQTT brokers for two different authentication systems. They
do not interoperate.

| | Public Developer API | Private API |
|-|----------------------|-------------|
| **Broker** | `mqtt-e.ecoflow.com:8883` (EU) / `mqtt.ecoflow.com:8883` (US) | `mqtt.ecoflow.com:8883` |
| **Auth entry point** | `GET /iot-open/sign/certification` (signed) | `POST /auth/login` + `GET /iot-auth/app/certification` |
| **MQTT credentials** | `certificateAccount` + `certificatePassword` | `certificateAccount` + `certificatePassword` |
| **Wire format** | JSON | Protobuf binary |
| **Encryption** | None (TLS wraps the connection) | XOR per-byte on Protobuf `pdata` when `enc_type==1` |
| **Devices** | STREAM Ultra (BK11), STREAM AC Pro (BK31), Smart Plug (HW52), Smart Meter (BK21), DELTA/RIVER batteries | Wave 3 AC (AC71) |
| **Entry point class** | `EcoFlowClient` | `Wave3Connection` |

Despite having the same field names (`certificateAccount`, `certificatePassword`), the credentials
from the public `/certification` endpoint are **not interchangeable** with credentials from the
private `/iot-auth/app/certification` endpoint.

---

## Public API MQTT

### Getting Credentials

Call the certification endpoint, signed the same way as any REST call (HMAC-SHA256):

```
GET https://api-e.ecoflow.com/iot-open/sign/certification   (EU)
GET https://api.ecoflow.com/iot-open/sign/certification     (US)
```

Headers required (see `auth.py` `build_auth_headers`):
- `accessKey`: your developer access key
- `timestamp`: Unix milliseconds as string
- `nonce`: random 6-digit string
- `sign`: HMAC-SHA256 of `sorted_query_params&accessKey=X&nonce=Y&timestamp=Z`

Response fields you actually need:
```json
{
  "data": {
    "url": "mqtt-e.ecoflow.com",
    "port": "8883",
    "protocol": "mqtts",
    "certificateAccount": "open-0123456789abcdef...",
    "certificatePassword": "REDACTED..."
  }
}
```

**What is NOT returned:** a `clientId`. You must generate one (see Stable Client IDs below).

### Connection Parameters

```python
import ssl
import aiomqtt

tls_context = ssl.create_default_context()
async with aiomqtt.Client(
    hostname="mqtt-e.ecoflow.com",   # from API response "url" field
    port=8883,
    username=certificate_account,    # from API response
    password=certificate_password,   # from API response
    identifier=client_id,            # your stable, deterministic ID
    keepalive=60,
    tls_context=tls_context,
) as client:
    ...
```

### Topic Patterns

All topics use `certificateAccount` (the MQTT username) as `{user_id}`:

| Purpose | Pattern | Direction |
|---------|---------|-----------|
| Device telemetry | `/open/{user_id}/{sn}/quota` | Device → you |
| Device status | `/open/{user_id}/{sn}/status` | Device → you |
| Send command | `/open/{user_id}/{sn}/set` | You → Device |
| Command ACK | `/open/{user_id}/{sn}/set_reply` | Device → you |

Subscribe to the quota topic at QoS 1:
```python
await client.subscribe(f"/open/{certificate_account}/{sn}/quota", qos=1)
```

Publish commands as JSON at QoS 1:
```python
payload = json.dumps({"params": {"switch": True}})
await client.publish(f"/open/{certificate_account}/{sn}/set", payload, qos=1)
```

### Payload Format (JSON)

Incoming telemetry on the quota topic:
```json
{
  "params": {
    "permanentWatts": 120.5,
    "dynamicWatts": 115.0,
    "gridStatus": 1
  }
}
```

Outgoing commands on the set topic:
```json
{
  "params": {
    "switch": true
  }
}
```

Field names match the REST `/iot-open/sign/device/quota/all` response for the same device.

---

## STREAM Device Write Commands

STREAM devices require a specific command envelope for ALL write operations. Missing any of
the envelope fields causes the device to silently ignore the command.

### Required Envelope

```json
{
  "from": "ecoflow-python",
  "id": "1",
  "version": "1.0",
  "sn": "BK11XXXXXXXXXX",
  "cmdId": 17,
  "cmdFunc": 254,
  "dirDest": 1,
  "dirSrc": 1,
  "dest": 2,
  "needAck": true,
  "params": {
    "cfgRelay2Onoff": true
  }
}
```

Note: `params` uses `cfg`-prefixed field names for write operations (e.g. `cfgRelay2Onoff`),
while the STATUS fields in telemetry use the plain name (e.g. `relay2Onoff`). These are
different field names — the `cfg` prefix means "configure".

Source: tolwi/hassio-ecoflow-cloud stream_ac.py (production-validated).

---

## ⚠️ Public API Quota Limits — Read This Before Writing Any MQTT Code

### Limit 1: ~10 Unique Client IDs Per Day Per Account

The EcoFlow MQTT broker tracks how many distinct client IDs have connected per `certificateAccount`
within the current UTC day. The limit is approximately 10. When you hit it:

- Every subsequent connection attempt returns error 135 (MQTT "Not Authorised")
- Error 135 persists for ALL connections with that `certificateAccount` until the daily reset
- The reset occurs at **midnight UTC**
- There is no override, no retry that helps, no support ticket that clears it faster

**How to burn through 10 slots in minutes:**
```python
# BAD — This is what the original library code did
import uuid
client_id = f"ANDROID_{uuid.uuid4().hex.upper()}"
# Every restart, every test, every retry = new unique ID = one slot consumed
```

Three test runs with reconnect retries = 15+ unique IDs = quota exhausted by mid-morning.

**The fix — stable deterministic client IDs:**
```python
import hashlib

# Public API: hash of certificateAccount
_suffix = hashlib.sha256(certificate_account.encode()).hexdigest()[:12]
client_id = f"ecoflow-sdk-{_suffix}"
# Same string every single restart, forever. One slot, no matter how many reconnects.
```

**Rules:**
- Never use `uuid4()`, `uuid.uuid4()`, PIDs, timestamps, or random strings in client IDs
- One application, one stable client ID, forever
- If you must run multiple applications with the same account, keep the total number of distinct
  IDs across all apps well under 10 per day

### Limit 2: One Active Session Per certificateAccount

Only one MQTT session can be active at a time per `certificateAccount`. If another client is
connected:

- Your new connection attempt gets error 135 immediately
- This happens even if your credentials are 100% correct
- The other client does NOT get notified (it stays connected)

**Practical consequences:**
- Running this library + openclaw (or any other EcoFlow integration) simultaneously → error 135
- Running two instances of this library simultaneously → error 135
- Running the library on a dev machine while Home Assistant runs on a server → error 135

**To run multiple apps:** stop one, start the other. There is no "sharing" mode.

### Diagnosing Error 135

Error 135 has two distinct causes. Diagnose before acting:

```
Scenario A: Another app is running with the same certificateAccount
  → Stop the other app
  → Retry your connection
  → Should succeed immediately

Scenario B: Daily quota exhausted (no other app is running)
  → Stop ALL connection attempts immediately
  → Do NOT retry — you cannot fix this with retries
  → Wait for midnight UTC
  → Connect once with your stable client ID
  → Should succeed
```

### Library Behaviour on Error 135

In `transport/mqtt.py`, error 135 handling differs by connection history:

**First connect returns 135:** Immediately raises `EcoFlowConnectionError` — no retry. The error
message explains what happened and what to do.

**Subsequent reconnect returns 135:** Retries with exponential backoff (1s → 2s → … → 300s cap).
This covers the case where a working session was transiently interrupted and the session slot was
briefly claimed by another client, which is a recoverable condition.

### Sharing Credentials With Other Applications

If you use the same developer `access_key`/`secret_key` in multiple applications, they will
derive the same `certificateAccount` from `/certification`. You have several options:

1. **Serialise them:** Run only one at a time. Stop one, start the other.
2. **Separate API keys:** Request separate developer API keys from EcoFlow for each application.
   Each key gets its own `certificateAccount` with its own quota.
3. **Proxy architecture:** One dedicated MQTT client that subscribes to all devices, and other
   applications connect to the proxy rather than the EcoFlow broker directly.

Option 2 is the cleanest for production multi-service deployments.

---

## Private API MQTT (Wave 3 Only)

### Why a Separate System

The Wave 3 AC (SN prefix `AC71`) is not supported by EcoFlow's public Developer API. Querying
it through the public API returns error 1006. EcoFlow's mobile app uses a separate, undocumented
API with different auth and Protobuf wire format. This library implements that private path for
Wave 3 support, derived from the open-source
[tolwi/hassio-ecoflow-cloud](https://github.com/tolwi/hassio-ecoflow-cloud) implementation.

### Getting Credentials (Two-Step Flow)

#### Step 1: Login

```
POST https://api.ecoflow.com/auth/login
Content-Type: application/json
lang: en_US

{
  "email": "you@example.com",
  "password": "<base64-encoded password>",
  "scene": "IOT_APP",
  "userType": "ECOFLOW"
}
```

**Critical:** the password must be base64-encoded. Plain text fails silently.
`"scene"` and `"userType"` are required. Without them the response structure is different.

```python
import base64
b64_password = base64.b64encode(password.encode()).decode()
```

Successful response extracts `token` and `userId`:
```json
{
  "code": "0",
  "data": {
    "token": "eyJhb...",
    "user": {"userId": "1234567890"}
  }
}
```

#### Step 2: MQTT Certification

```
GET https://api.ecoflow.com/iot-auth/app/certification
Authorization: Bearer <token>
lang: en_US
Content-Type: application/json

userId=<userId>    ← form-encoded body (NOT JSON)
```

**Critical:** this is a `GET` request with a form-encoded body. Standard HTTP libraries don't
support GET + body through their shorthand methods. Use the low-level `.request()` method:

```python
# httpx
resp = await client.request(
    "GET", url,
    data={"userId": user_id},   # form-encoded body
    headers={"Authorization": f"Bearer {token}", ...}
)
```

Sending `json={"userId": user_id}` on a GET request is silently ignored by the server.

Successful response:
```json
{
  "code": "0",
  "data": {
    "certificateAccount": "open-012345...",
    "certificatePassword": "REDACTED..."
  }
}
```

### Connection Parameters

```python
import hashlib, ssl
import aiomqtt

# Stable client ID from userId (not certificateAccount)
_hash = hashlib.sha256(user_id.encode()).hexdigest()[:12]
client_id = f"ecoflow-private-{_hash}"

tls_ctx = ssl.create_default_context()
async with aiomqtt.Client(
    hostname="mqtt.ecoflow.com",    # NOT mqtt-e.ecoflow.com
    port=8883,
    username=certificate_account,
    password=certificate_password,
    identifier=client_id,
    keepalive=60,
    tls_context=tls_ctx,
) as client:
    ...
```

### Topic Patterns

| Purpose | Pattern | Direction |
|---------|---------|-----------|
| Device telemetry | `/app/device/property/{sn}` | Device → you |
| Send command | `/app/{userId}/{sn}/thing/property/set` | You → Device |
| GET trigger | `/app/{userId}/{sn}/thing/property/get` | You → Device |

Note: the telemetry topic uses only `{sn}`, not `{userId}/{sn}`. The command topics use `{userId}`.

### Triggering the Initial State Dump

After subscribing to the telemetry topic, the device is **completely silent** until it receives
a GET request. Subscribe first, then publish the trigger immediately after:

```python
# Subscribe
await client.subscribe(f"/app/device/property/{sn}", qos=1)

# Trigger state dump
trigger_topic = f"/app/{user_id}/{sn}/thing/property/get"
trigger_payload = json.dumps({
    "version": "1.0",
    "sn": sn,
    "moduleType": 0,
    "operateType": "get",
    "params": {}
}).encode()
await client.publish(trigger_topic, trigger_payload, qos=1)
```

Without this, `device.status` will remain `None` indefinitely even with a healthy connection.

### Payload Format (Protobuf)

Incoming messages on `/app/device/property/{sn}` are binary Protobuf. The outer envelope is a
`PowerMessage` with:
- `src`: message source (32 = app/our commands; other values = device telemetry)
- `cmd_func`: command function number
- `cmd_id`: command ID
- `seq`: sequence number (used for XOR decryption key)
- `enc_type`: encryption type (0 = none, 1 = XOR)
- `pdata`: inner Protobuf payload (may be XOR-encrypted)

**XOR decryption:** when `enc_type == 1 AND src != 32`:
```python
pdata = bytes(b ^ (msg.seq & 0xFF) for b in msg.pdata)
```
When `src == 32`, the message is a command echo from our own app — do not decrypt.

After decryption, dispatch `pdata` based on `(cmd_func, cmd_id)`:
- `(254, 1)` or `(254, 21)` → `Wave3DisplayPropertyUpload` (full device state)
- `(254, 22)` → `Wave3RuntimePropertyUpload` (temperature/runtime update)

All of this is handled transparently by `private/proto/decoder.py`.

**Outgoing commands** on the set topic are also Protobuf-encoded `Wave3SetMessage` structs.
Use `private/proto/encoder.py` `build_command()` to construct them.

### Battery SOC Is 0.0 in Standby

When the Wave 3 is in standby (`dev_sleep_state == 1`), the device sends partial Protobuf
updates that do not include the `bms_batt_soc` field. The field defaults to `0.0` in the decoded
struct. This is not a real reading — it is a missing field. Only read `battery_soc` when
`is_on == True`.

### Temperature Fields Are Native °C

`temp_set` and related temperature fields in the Wave 3 Protobuf schema are declared as `float`
in native degrees Celsius. A value of `24.0` means 24°C. The ×10 encoding (`240` = 24°C) appears
in EcoFlow's older JSON API for some battery devices and should not be applied here.

---

## Common Mistakes and How to Avoid Them

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Random UUID client IDs | Burns daily quota in minutes | Use deterministic SHA-256 hash of account |
| Running two apps simultaneously | Error 135 for the second app | Stop one before starting the other |
| Retrying on error 135 | Makes quota exhaustion worse if IDs vary | Fail fast, wait for midnight UTC |
| Not sending GET trigger (Wave 3) | Device never sends data, status is None forever | Library sends it automatically; don't bypass `Wave3Connection` |
| Plain text password in login (Wave 3) | Silent auth failure (wrong credentials error) | `base64.b64encode(password.encode()).decode()` |
| JSON body on GET certification (Wave 3) | Server ignores it, cert call silently fails | Use form-encoded body with `.request("GET", ...)` |
| Using public broker for Wave 3 | No data received (wrong topic format) | Use `mqtt.ecoflow.com`, not `mqtt-e.ecoflow.com` |
| `cfg_main_power=True` alone to turn on | Device wakes but `is_on` stays False | Also send `cfg_wave_operating_mode=1` (COOLING) |
| Reading `battery_soc` in standby | Always 0.0 — device doesn't send it | Check `is_on` first |

---

## Debugging Connection Issues

### Checklist for Error 135

```
1. Is another app (openclaw, Home Assistant, another script) connected?
   YES → Stop it, then retry
   NO  → Daily quota is exhausted; see step 3

2. Is your client ID stable (same hash every restart)?
   NO  → Fix client ID generation first (see AGENTS.md Quirk 1)
   YES → Continue

3. Quota exhausted. Stop all connection attempts now.
   Every failed attempt may burn another slot if client ID varies.
   
4. Wait for midnight UTC.

5. Reconnect with ONE stable client ID.
   Verify it connects successfully before continuing.
```

### How to Verify Your Client ID Is Stable

```python
import hashlib

# Verify this prints the same string every time
certificate_account = "open-0123456789abcdef..."
suffix = hashlib.sha256(certificate_account.encode()).hexdigest()[:12]
print(f"ecoflow-sdk-{suffix}")
# Should always print: ecoflow-sdk-a1b2c3d4e5f6 (same hash, every run)
```

### Checking Live MQTT Connection Without Burning Quota

If you need to test MQTT credentials without risking a quota slot, verify the REST certification
endpoint first — it's quota-free:

```bash
# Test that credentials produce valid certificateAccount
python -c "
import asyncio
from ecoflow import EcoFlowClient

async def test():
    async with EcoFlowClient('YOUR_KEY', 'YOUR_SECRET', region='EU') as c:
        print('REST OK, devices:', [d.sn for d in c.batteries + c.plugs + c.meters])
asyncio.run(test())
"
```

Only attempt MQTT after confirming REST works and you have a stable client ID configured.

### Logging MQTT Activity

Enable debug logging to see connection events and message routing:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("ecoflow.transport.mqtt").setLevel(logging.DEBUG)
logging.getLogger("ecoflow.private.connection").setLevel(logging.DEBUG)
```

This will log connection attempts, subscription confirmations, and per-message routing without
exposing credential values.

---

## Integration Scenarios

### Scenario A: Library Alongside openclaw

openclaw uses a hardcoded `mqtt_username`/`mqtt_password` from its config — the same
`certificateAccount`/`certificatePassword` this library fetches from `/certification`. They are
the same account and cannot be simultaneously connected.

**Pattern:**
1. Stop openclaw before starting the library
2. Use the library for reads/writes
3. Restart openclaw when done

Or: get separate developer API keys from EcoFlow so each application has its own account.

### Scenario B: Library Alongside Home Assistant EcoFlow Integration

Same constraint. The HA EcoFlow integration also uses the same MQTT credentials. They cannot
coexist. Use separate API keys.

### Scenario C: Multiple Devices, One Connection

The library handles this correctly — `EcoFlowClient.connect()` discovers all devices and
subscribes to all device topics in a single MQTT session:

```python
async with EcoFlowClient(access_key, secret_key, region="EU") as client:
    # One MQTT connection, all devices subscribed
    for plug in client.plugs:
        print(plug.sn, plug.status)
    for battery in client.batteries:
        print(battery.sn, battery.status)
```

Do NOT create one `EcoFlowClient` per device — that would attempt multiple simultaneous sessions.

### Scenario D: Wave 3 + Other Devices

The Wave 3 uses the private API; all other devices use the public API. Run both simultaneously
(they use different brokers and different credentials):

```python
import asyncio
from ecoflow import EcoFlowClient
from ecoflow.private import Wave3Connection

async def main():
    async with (
        EcoFlowClient(access_key, secret_key, region="EU") as public_client,
        Wave3Connection(email, password, ["AC71XXXXXXXXXX"]) as wave3,
    ):
        # Public API devices (STREAM, Smart Plug, etc.)
        for plug in public_client.plugs:
            print("Plug:", plug.status)
        
        # Wave 3
        wave3_device = wave3.devices["AC71XXXXXXXXXX"]
        await asyncio.sleep(3)  # wait for first Protobuf push
        print("Wave 3:", wave3_device.status)

asyncio.run(main())
```

These two connections use different `certificateAccount` values (public vs private API) and
different brokers, so there is no conflict.
