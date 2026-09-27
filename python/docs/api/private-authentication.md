# Private API Authentication (Wave 3)

Wave 3 portable AC units (serial number prefix `AC71`) are **not supported** by the
EcoFlow Developer API. Any REST query for a Wave 3 device returns error **1006**
("device not supported"). To monitor or control a Wave 3, use `Wave3Connection` from
the `ecoflow.private` subpackage — it authenticates with the EcoFlow mobile-app API
and communicates over a Protobuf MQTT channel.

> **Note:** All other EcoFlow devices (Delta, River, PowerStream, …) continue to use
> `EcoFlowClient` with `accessKey`/`secretKey` from the Developer Portal.
> See [Authentication](authentication.md) for that flow.

---

## Installation

The `ecoflow.private` subpackage requires `protobuf>=4.0`, which is not installed by
default. Install the `wave3` extra:

```sh
pip install ecoflow-python[wave3]
```

If you try to `import ecoflow.private` without the extra, a clear `ImportError` is
raised with the install command above — not a silent failure at runtime.

---

## Quick Start

```python
import asyncio
from ecoflow.private import Wave3Connection

async def main() -> None:
    async with Wave3Connection(
        email="me@example.com",
        password="my_password",       # see Security note below
        device_sns=["AC71XXXXXXXXXXXX"],
    ) as wave3:
        sn = "AC71XXXXXXXXXXXX"
        device = wave3.devices[sn]

        # The device pushes status over MQTT — wait for the first message.
        await asyncio.sleep(10)

        status = device.status
        print(status.battery_soc)        # e.g. 87.0  (%)
        print(status.mode.name)          # e.g. "COOLING"
        print(status.ambient_temp)       # e.g. 24.5  (°C, native float)

asyncio.run(main())
```

`Wave3Connection` is an async context manager: `__aenter__` calls `connect()`,
which authenticates, populates `wave3.devices`, and waits (up to 15 s) for the MQTT
subscription to be acknowledged. `__aexit__` calls `close()`, which cancels the
background MQTT task cleanly.

---

## How It Works

The library performs six steps when you open a `Wave3Connection`:

1. **POST `https://api.ecoflow.com/auth/login`** — sends `{email, password}` and
   receives `certificateAccount` (MQTT username) and `certificatePassword` (MQTT
   password) along with a `userId`.

2. **Exchange for MQTT credentials** — `certificateAccount` and `certificatePassword`
   are the credentials used directly to connect to the MQTT broker. No further token
   exchange is needed.

3. **aiomqtt connects to `mqtt.ecoflow.com:8883`** — TLS is enabled via
   `ssl.create_default_context()`. The MQTT `client_id` is built as
   `f"ANDROID_{uuid.uuid4().hex.upper()}_{creds.user_id}"` — this exact format
   is required by the private broker; any other format results in MQTT error 135
   (Not authorized).

4. **Subscribes to `/app/device/property/{sn}` at QoS 1** — one subscription per
   device serial number in `device_sns`.

5. **Protobuf decode (with possible XOR)** — each inbound message passes through
   `ecoflow.private.proto.decoder.decode()`:
   - The outer `Wave3SetMessage` envelope is parsed.
   - If `enc_type=1` and `src≠32`: `pdata` is XOR-decrypted with `seq & 0xFF`.
   - The inner payload is dispatched by `cmd_func`/`cmd_id` and flattened to a
     `dict[str, Any]`.

6. **`Wave3Device._handle_message()` → `device.status`** — the decoded dict is
   merged into the device's `Wave3Status`, updating fields like `battery_soc`,
   `mode`, `ambient_temp`, and `is_on`.

---

## Private API vs Developer API

| | Private API | Public Developer API |
|---|---|---|
| **Auth input** | `email` + `password` (EcoFlow app account) | `accessKey` + `secretKey` |
| **Where to get credentials** | Any EcoFlow app account | [developer.ecoflow.com](https://developer.ecoflow.com) / [developer-eu.ecoflow.com](https://developer-eu.ecoflow.com) |
| **MQTT broker** | `mqtt.ecoflow.com` (global) | `mqtt-e.ecoflow.com` (EU) or `mqtt.ecoflow.com` (US) |
| **Wave 3 support** | Yes | No — returns error 1006 |
| **Other device support** | Not confirmed for Wave 2 or other devices | Yes (Delta, River, PowerStream, …) |

---

## Security Note

Your EcoFlow **password is a secret** — treat it the same as an API key or database
credential.

**Do not commit passwords to source control.** Store credentials in environment
variables or a `.env` file (gitignored):

```sh
# .env  — add this file to .gitignore
ECOFLOW_EMAIL=me@example.com
ECOFLOW_PASSWORD=my_password
ECOFLOW_WAVE3_SN=AC71XXXXXXXXXXXX
```

```python
import os
from dotenv import load_dotenv
from ecoflow.private import Wave3Connection

load_dotenv()

async with Wave3Connection(
    email=os.environ["ECOFLOW_EMAIL"],
    password=os.environ["ECOFLOW_PASSWORD"],
    device_sns=[os.environ["ECOFLOW_WAVE3_SN"]],
) as wave3:
    ...
```

Never commit a `.env` file. Add it to `.gitignore` and use a secrets manager or CI
environment variables in production.

---

## Regions

The private API endpoint and MQTT broker are **global** — the same URL for both EU
and US accounts:

| | URL |
|---|---|
| Auth endpoint | `https://api.ecoflow.com/auth/login` |
| MQTT broker | `mqtt.ecoflow.com:8883` |

> **Do not use `mqtt-e.ecoflow.com`** for the private API. That host is the EU MQTT
> broker for the *public* Developer API. The private API always uses
> `mqtt.ecoflow.com` regardless of region.

---

## Reconnection

`Wave3Connection` reconnects automatically if the MQTT connection drops. The
reconnection uses **exponential backoff**:

| Attempt | Wait before retry |
|---------|-------------------|
| 1 | 1s |
| 2 | 2s |
| 3 | 4s |
| 4 | 8s |
| … | doubles each time |
| cap | 300s |

The backoff counter resets to 1s after a successful reconnection. Authentication
credentials are reused — no re-login is performed on reconnect.

---

## Open Questions / Known Limitations

- **Write commands not yet implemented.** Setting temperature, mode, or fan speed via
  the private MQTT API requires encoding Protobuf command messages — this is deferred
  to a future release. Calling write commands currently raises `EcoFlowConnectionError`.

- **Token expiry is undocumented.** Private credentials (`certificateAccount` /
  `certificatePassword`) appear long-lived, but the actual expiry behaviour is
  undocumented by EcoFlow. No automatic re-login is implemented; if you observe
  authentication failures after a long session, restart the connection.

- **Other devices (Wave 2, Glacier, etc.) are not confirmed.** This library is
  intentionally scoped to Wave 3 (`AC71` prefix). Wave 2 and other devices excluded
  from the Developer API may follow a similar private protocol, but this has not been
  verified. A device owner capturing raw MQTT payloads would be needed to add support.
