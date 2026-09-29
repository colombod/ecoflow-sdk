# AGENTS.md — ecoflow-python

> Real-world battle notes from building and debugging this library against live hardware.
> Read this before touching any MQTT or authentication code.
> If you skip this and go straight to the code, you will burn the daily MQTT quota within minutes.

---

## What This Library Does

`ecoflow-python` is a typed async Python SDK for monitoring and controlling EcoFlow energy
devices. It provides **two completely separate API paths** that share nothing:

1. **Public Developer API** (`EcoFlowClient`): accessKey/secretKey, REST + JSON MQTT, covers most
   devices (STREAM Ultra, STREAM AC Pro, Smart Plug, Smart Meter, DELTA/RIVER battery series).
2. **Private API** (`Wave3Connection`): email/password, Protobuf MQTT, required for Wave 3 AC units
   because EcoFlow's public API returns error 1006 for that model family.

---

## Codebase Map

### Source Structure

```
src/ecoflow/
├── client.py         — EcoFlowClient: main entry point, device discovery, MQTT orchestration
├── auth.py           — EcoFlowCredentials, HMAC-SHA256 signing (build_auth_headers)
├── const.py          — REST hosts, endpoints, SN→model map (SN_PREFIX_TO_MODEL), DeviceModel enum
├── exceptions.py     — 7 exception types (EcoFlowError hierarchy)
├── transport/
│   ├── rest.py       — RestTransport (httpx, signed REST calls)
│   └── mqtt.py       — MqttTransport (aiomqtt, TLS, stable client IDs, fail-fast 135 handling)
├── devices/          — 9 device classes (BaseDevice + 8 typed subclasses) + DiscoveredDevice
├── models/           — Pure dataclass status snapshots per device type
└── private/          — Wave 3 private API (optional, requires protobuf extra)
    ├── auth.py       — login(email, password) → PrivateCredentials (2-step, base64 password)
    ├── connection.py — Wave3Connection (direct aiomqtt, Protobuf, stable client IDs)
    └── proto/        — decoder.py, encoder.py, wave3_pb2.py (vendored Protobuf schema)

src/ecoflow_twin/     — Service digital twin (extra: twin). Never imported by ecoflow.
├── recording.py      — Load/validate tests/recordings/*/recording.json
├── timeline.py       — Time-compressed, looping playback of recorded pushes
├── certs.py          — Local CA + server cert (SANs: localhost/127.0.0.1/EcoFlow hosts)
├── signing.py        — EcoFlow's REST signature rule, independent of ecoflow.auth
├── state.py          — Recorded bodies + command effects (only live-verified ones)
├── rest.py           — HTTPS Developer API (aiohttp): list, quota/all, certification
├── mqtt_codec.py     — MQTT 3.1.1 packet codec (EcoFlow's client subset)
├── broker.py         — MQTT broker: Quirk 1/2/3 refusals (CONNACK 5 = 135), playback, /set
├── server.py         — TwinServer / TwinEndpoints: compose on local TLS ports
└── cli.py            — ecoflow-twin serve --recording PATH  (prints endpoints as JSON)
```

### Device Classes (`devices/`)

| File | Class | Collection on `EcoFlowClient` |
|------|-------|-------------------------------|
| `base.py` | `BaseDevice` | — (abstract base) |
| `battery.py` | `BatteryDevice` | `client.batteries` |
| `plug.py` | `SmartPlugDevice` | `client.plugs` |
| `meter.py` | `SmartMeterDevice` | `client.meters` |
| `inverter.py` | `MicroInverterDevice` | `client.inverters` |
| `wave3.py` | `Wave3Device` | `client.wave3_units` |
| `stream_ultra.py` | `StreamUltraDevice` | `client.stream_units` |
| `stream_ac_pro.py` | `StreamAcProDevice` | `client.stream_units` (subclass of `StreamUltraDevice`) |
| `panel.py` | `SmartHomePanelDevice` | none — tracked in internal `_all_typed` only |
| `discovered.py` | `DiscoveredDevice` | `client.unknown_devices` |

### Model Classes (`models/`)

| File | Dataclass | Used by |
|------|-----------|---------|
| `battery.py` | `BatteryStatus`, `BmsModule`, `ExpansionBatteryModule`, `SolarInput` | `BatteryDevice` |
| `plug.py` | `SmartPlugData` | `SmartPlugDevice` |
| `meter.py` | `SmartMeterData` | `SmartMeterDevice`, `MicroInverterDevice` |
| `wave3.py` | `Wave3Status`, `Wave3Mode` | `Wave3Device`, `Wave3Connection` |
| `stream_ultra.py` | `StreamUltraStatus` | `StreamUltraDevice`, `StreamAcProDevice` |

### Exception Hierarchy (`exceptions.py`)

```
EcoFlowError                    ← base; catch-all
├── EcoFlowAuthError            ← bad API keys or bad credentials
├── EcoFlowConnectionError      ← network / transport failure (also MQTT quota errors)
├── EcoFlowDeviceNotFoundError  ← SN not on account (carries .sn attr)
├── EcoFlowTimeoutError         ← command or query timed out
├── EcoFlowDeviceOfflineError   ← action on offline device (carries .sn attr)
└── EcoFlowCommandError         ← device rejected a command
```

### Test Structure

```
tests/
├── test_*.py                         — Unit tests (mocked, no real devices, ~400 tests)
│   ├── test_models_wave3_private.py  — ACTIVE_PAYLOAD/STANDBY_PAYLOAD fixtures from real device
│   ├── test_private_decoder.py       — XOR decryption + Protobuf dispatch tests
│   └── test_recordings.py            — Per-recording MQTT-vs-REST agreement over the twin, PII guard
├── conftest.py                       — --live tier gate + credential helpers
├── support/consistency.py            — MQTT-vs-REST stable-field comparison (live + offline)
├── support/recordings.py             — RECORDINGS_DIR / all_recordings() for the suites
├── twin/                             — Service twin unit + behaviour tests (real aiomqtt/httpx clients)
├── recordings/<name>/recording.json  — Redacted real sessions (+ synthetic/) replayed by --live=replay
└── e2e/
    ├── conftest.py                   — public_creds / rest_client / mqtt_client fixtures
    ├── test_live_rest.py             — Tier 1: REST only (--live=rest; replayable)
    ├── test_live_mqtt.py             — Tier 2: MQTT agrees with REST (--live=mqtt; replayable)
    ├── test_read.py                  — Read integration tests (real devices, @pytest.mark.integration)
    ├── test_private_read.py          — Wave 3 private API read tests (@pytest.mark.integration)
    └── write/                        — Write tests (@pytest.mark.write_integration,
        │                               requires ECOFLOW_ENABLE_WRITE_TESTS=true AND
        │                               --enable-write-tests CLI flag — both needed)
        ├── test_wave3_commands.py    — Wave 3 (private API)
        ├── test_stream_relay_commands.py — STREAM relay2/relay3
        └── test_write_plug.py        — Smart Plug on/off
```

---

## The Two API Paths — Never Mix Them

### Public Developer API (accessKey + secretKey)

**Auth flow:**
1. Get `access_key` and `secret_key` from the [EcoFlow Developer Portal](https://developer.ecoflow.com)
2. Every REST call is HMAC-SHA256 signed: sorted query params + `accessKey` + `nonce` + `timestamp`
3. Call `GET /iot-open/sign/certification` (signed) to get `certificateAccount` + `certificatePassword`
4. Use those as MQTT username/password

**Supported SN prefixes (confirmed live):**
- `BK11` → STREAM Ultra
- `BK31` → STREAM AC Pro
- `BK21` → Smart Meter
- `HW52` → Smart Plug
- `AC71` → Wave 3 (discovered but error 1006 on data endpoints — use private API)
- DELTA/RIVER battery families — `productName` returned by device list API

**REST endpoints:**
- EU: `https://api-e.ecoflow.com/iot-open/sign/...`
- US: `https://api.ecoflow.com/iot-open/sign/...`

**MQTT broker:**
- EU: `mqtt-e.ecoflow.com:8883` (TLS)
- US: `mqtt.ecoflow.com:8883` (TLS)
- The `/certification` response includes the correct `url` for your region — use it, don't hardcode

**Topic patterns (public API):**
- Status push: `/open/{certificateAccount}/{sn}/quota`
- Commands:    `/open/{certificateAccount}/{sn}/set`
- Replies:     `/open/{certificateAccount}/{sn}/set_reply`

### Private API (email + password — Wave 3 only)

**Auth flow (two steps):**
1. `POST https://api.ecoflow.com/auth/login` with base64-encoded password → bearer token + userId
2. `GET https://api.ecoflow.com/iot-auth/app/certification` with `Authorization: Bearer {token}`
   and `userId` as form-encoded body → `certificateAccount` + `certificatePassword`

**Supported devices:** Wave 3 AC (SN prefix `AC71`)

**MQTT broker:** `mqtt.ecoflow.com:8883` (TLS) — **DIFFERENT from the EU public broker**

**Topic patterns (private API):**
- Status push: `/app/device/property/{sn}` (Protobuf binary)
- Commands:    `/app/{userId}/{sn}/thing/property/set`
- GET trigger: `/app/{userId}/{sn}/thing/property/get`

---

## 🚨 MQTT QUIRKS — Read Before Touching mqtt.py or client.py

This section documents every hard-won discovery from live hardware testing. Each quirk cost at
least one debugging session. Do not repeat these mistakes.

### Quirk 1: Daily Client ID Quota (~10 unique IDs/day)

**Discovered 2026-05-31.** The EcoFlow MQTT broker enforces approximately **10 unique MQTT client
IDs per day per `certificateAccount`**. When this limit is exhausted, ALL connection attempts
return error 135 until the daily quota resets at midnight UTC.

**How we burned it:** The original code used `uuid4()` to generate a fresh random UUID on every
connection attempt. Each failed probe, each test run, each reconnect retry counted as a new unique
ID. Within one debugging session (~20 connection attempts), the entire day's quota was gone.

**The fix (PR #6 commit "fix: use stable deterministic MQTT client ID to avoid EcoFlow 10-ID/day quota", squash-merged as "feat: STREAM relay commands — validated against real BK11/BK31 hardware"):** Client IDs are now deterministic and stable:
```python
# Public API — derived from certificateAccount
_stable_suffix = hashlib.sha256(account.encode()).hexdigest()[:12]
client_id = f"ecoflow-sdk-{_stable_suffix}"

# Private API — derived from userId, in the only shape the app broker accepts
client_id = private_client_id(user_id)  # ANDROID_<sha256(userId)[:32].upper()>_<userId>
```
One slot used, regardless of how many times the library reconnects.

**Amended 2026-09-28 (PR #11):** that PR #6 commit changed the private ID to
`ecoflow-private-<hash>`. It was stable, but the app broker answers 135 to any ID not shaped
`ANDROID_<32 hex>_<userId>`, so every Wave 3 connection failed from 0.3.0 until the shape was
restored. Keep **both** properties: stable *and* the broker's shape
(`docs/decisions/0002-stable-mqtt-client-ids.md`).

**If you see error 135 with nothing else connected:**
1. Stop ALL connection attempts immediately. Every retry burns another slot if the client ID
   somehow changes (it shouldn't with the fix, but verify).
2. Wait until midnight UTC for the daily reset.
3. Then connect once with the stable ID and verify it works.

**NEVER use `uuid4()`, timestamps, PIDs, or any per-run suffix in MQTT client IDs.**

### Quirk 2: Only One Active MQTT Session Per certificateAccount

**Discovered 2026-05-31.** The broker allows exactly one active session per `certificateAccount`.
If another application already holds a session using the same credentials (e.g., openclaw,
Home Assistant, another script), new connection attempts receive error 135 immediately — even with
correct credentials.

**This is a different root cause from Quirk 1.** The broker uses error 135 for both:
- "Quota of unique client IDs exhausted today" (Quirk 1)
- "Another session is already connected with these credentials" (this Quirk)

**Diagnosis:**
```
Error 135 + another app is running with same certificateAccount → session conflict → stop the other app
Error 135 + nothing else running → quota exhausted → wait for midnight UTC
```

**Practical implication:** You cannot run the library simultaneously with openclaw, Home Assistant,
or any other EcoFlow integration that uses the same API keys. Stop one before starting the other.

### Quirk 3: /certification Does Not Return clientId

**Discovered 2026-05-31.** The REST endpoint `GET /iot-open/sign/certification` returns
`certificateAccount` and `certificatePassword` but does **not** return a `clientId` field.

Old code that did `mqtt_data.get("clientId", "")` got an empty string. The broker rejects an
empty client ID with error 135. This looked like an auth failure but was a missing client ID.

**The fix:** Always generate a stable deterministic client ID if none is provided (see Quirk 1
for the exact formula). The code in `client.py` handles this:
```python
client_id = mqtt_data.get("clientId") or f"ecoflow-sdk-{_stable_suffix}"
```

### Quirk 4: Two Completely Different Brokers — Do Not Cross Them

| | Public API (EU) | Private API |
|-|-----------------|-------------|
| Broker | `mqtt-e.ecoflow.com:8883` | `mqtt.ecoflow.com:8883` |
| Wire format | JSON (flat or family-wrapped, see Quirk 14) | Protobuf binary |
| Auth | `certificateAccount` from `/certification` | `certificateAccount` from `/iot-auth/app/certification` |
| Topic | `/open/{certAccount}/{sn}/quota` | `/app/device/property/{sn}` |

`MqttTransport` calls `json.loads()` on every message. Pointing it at the private broker or Wave 3
topics will silently discard all Protobuf content — no error, no data, just silence.

### Quirk 5: Error 135 Is Fail-Fast on First Connect, Retry on Subsequent

**Implemented in `transport/mqtt.py`.** Behaviour differs by connection history:

- **First connect returns 135:** Immediately raises `EcoFlowConnectionError` with a diagnostic
  message. Does NOT retry — retrying with the same stable client ID against a quota-exhausted
  or session-conflicted broker will never succeed.
- **Subsequent reconnect returns 135:** Retries with exponential backoff (1s → 2s → … → 300s).
  This handles the case where a working session was temporarily interrupted and stolen, which
  is a transient condition.

The error message on first-connect failure explicitly tells the developer what happened and what
to do. Read it — it contains the diagnosis.

---

## 🚨 WAVE 3 PRIVATE API QUIRKS

### Quirk 6: Password Must Be Base64-Encoded Before Login

**Discovered during initial Wave 3 integration.** The `/auth/login` endpoint requires the
password to be `base64.b64encode(password.encode()).decode()` in the JSON body. Sending the
plain text password fails with a credentials error (not an encoding error — silent failure).

You also need `"scene": "IOT_APP", "userType": "ECOFLOW"` in the request body. Without these,
the response structure is completely different and the token extraction fails.

```python
# CORRECT
b64_password = base64.b64encode(password.encode()).decode()
json={"email": email, "password": b64_password, "scene": "IOT_APP", "userType": "ECOFLOW"}
```

### Quirk 7: Two-Step MQTT Certification (GET with a Body)

**Discovered during Wave 3 integration.** Unlike the public API (one REST call → MQTT creds),
the private API requires two steps:

1. `POST /auth/login` → bearer token + userId
2. `GET /iot-auth/app/certification` with `Authorization: Bearer {token}` and `userId` as
   **form-encoded** body

Step 2 is unusual: it's a `GET` request that sends a body. `httpx`'s `.get()` does not support
a body. Use `.request("GET", url, data={"userId": user_id}, ...)` instead. Sending `json=` on
a GET is silently ignored by the server, returning an empty or malformed response.

### Quirk 8: Device Is Silent Until You Send a GET Trigger

**Discovered during Wave 3 live testing.** After subscribing to `/app/device/property/{sn}`,
the Wave 3 sends **no data** until it receives a GET request on the command topic. Without this,
`device.status` remains `None` indefinitely — even with a working MQTT connection.

The library sends this trigger automatically after subscribing:
```python
topic = f"/app/{user_id}/{sn}/thing/property/get"
payload = {"version": "1.0", "sn": sn, "moduleType": 0, "operateType": "get", "params": {}}
await client.publish(topic, json.dumps(payload).encode(), qos=1)
```
If you bypass `Wave3Connection` and write direct MQTT code, you must send this yourself.

### Quirk 9: XOR Encryption on Incoming Messages

**Discovered during Protobuf decoder development.** Wave 3 Protobuf messages have an `enc_type`
field. When `enc_type == 1 AND src != 32`, the `pdata` bytes must be XOR'd with `(seq & 0xFF)`
before parsing. Messages where `src == 32` are commands sent by our app — they must **not** be
decrypted (they aren't encrypted to begin with).

```python
if msg.enc_type == 1 and msg.src != 32:
    pdata = bytes(b ^ (msg.seq & 0xFF) for b in msg.pdata)
else:
    pdata = msg.pdata
```
The decoder in `private/proto/decoder.py` handles this transparently. If you modify the decoder,
preserve this invariant exactly.

### Quirk 10: turn_on() Must Also Set the Operating Mode

**Discovered during Wave 3 write testing.** Sending only `cfg_main_power=True` does NOT fully
turn on the device. The `is_on` property is derived from **two** fields:
`dev_sleep_state != 1 AND wave_operating_mode != 0`.

Sending `cfg_main_power=True` alone wakes the device from sleep (dev_sleep_state becomes 0)
but leaves `wave_operating_mode = 0` (NONE), so `is_on` remains `False`.

The library's `turn_on()` sends both fields:
```python
build_command(sn, cfg_main_power=True, cfg_wave_operating_mode=1)  # 1 = COOLING
```
Do not "simplify" this to just `cfg_main_power=True`.

### Quirk 11: Temperature Fields Are Native °C (NOT ×10)

**Discovered and verified against real device.** Despite early assumptions and some community
documentation suggesting temperatures are ×10 encoded (e.g., `240` means `24°C`), the Wave 3
Protobuf schema declares `temp_set: float` — native degrees Celsius.

`wave_mode_info[mode].temp_set = 24.0` means **24°C**, not **2.4°C**.

The ×10 encoding appears in the older JSON API for other EcoFlow devices (some battery models).
Do not carry that assumption into Wave 3 code.

### Quirk 12: Battery SOC Is 0.0 in Standby — Not a Real Reading

**Discovered during Wave 3 standby testing.** When the Wave 3 is in standby
(`dev_sleep_state == 1`), the device sends partial Protobuf updates that do **not** include
`bms_batt_soc`. The Protobuf field defaults to `0.0`. This does NOT mean the battery is empty.

Real battery SOC values are only available after the device is active (`is_on == True`). Do not
display or act on `battery_soc` if `is_on` is `False`.

---

### Quirk 12b: The Full State Dump Arrives on the Device's Schedule (recorded 2026-09-28)

**Evidence:** 5 separate sessions recorded on 2026-09-28, with the EcoFlow app closed. The full
display message (`cmd_func 254 / cmd_id 21`, ~50 fields including `bms_batt_soc`) arrived
within 7 s in some sessions and **not within 66 s** in others. That held even when the GET
trigger (Quirk 8) was re-sent every 8 s, and with `operateType: "latestQuotas"` instead of
`"get"`. In between, the Wave 3 sends:

| Message | Content |
|---------|---------|
| `254/21`, 4 bytes | a single field (`bms_dsg_rem_time`) |
| `254/22` runtime | ~50 fields: `plug_in_info_ac_in_vol` (V), `bms_batt_vol` (mV), `bms_batt_amp` (mA, negative = discharge), BMS alarms and firmware. **The decoder discarded it before 2026-09-28.** |
| `32/50` every ~10 s | another module. Decoded with the Wave 3 schemas it produces nonsense (e.g. 99.99 W "AC in"); ignore it. |

**Measured cadence (10-minute passive recording, 2026-09-28):** the full display message arrived
at 60, 180, 300, 421 and 541 s, **exactly every 120 s**. The runtime message `254/22` arrives every
300 s. Changed fields arrive every ~2 s. One `latestQuotas` request with the
`/app/{userId}/{sn}/thing/property/get_reply` topic subscribed (the reference integration's method)
got **no reply** from the Wave 3.

**Verified reliable usage (live outlet test, 2026-09-28):** with one long-lived session, the first
complete status arrived at 31 s (SOC 89.43 %). Switching the feeding STREAM Ultra outlet (AC2,
`relay3`) off showed `ac_plugged_in=False` and battery power −18 W within ~2 s, and the next full
upload showed the SOC falling (89.43 → 89.26 %). Switching it back on showed charging ramp to +701 W
within 12 s.

**Consequences:**

- `Wave3Device` publishes no status until the SOC has been seen. Before that, the first partial
  messages read as "0 % / off" for ~20 s.
- Don't spam GETs to force a dump; it doesn't help (see the owner's rule on not blasting the
  service).
- `pow_get_ac_in` is **never sent**: it read 0 while the unit charged at ~700 W from AC. The AC
  power is `pow_get_ac` (equal to self-consumption while running from AC), and
  `plug_in_info_ac_in_flag` says whether AC is connected.
- `pow_get_bms` is positive when charging and negative when discharging. Verified by switching
  the unit's feeding STREAM outlet off (−18 W) and on (+700 W).

---

## 🚨 STREAM DEVICE QUIRKS

### Quirk 13: Commands Need Full Envelope (dirDest/dirSrc/dest/needAck/from/id/version)

**DISCOVERED: 2026-06-01.** STREAM devices silently ignore set commands that do not include
the full message envelope. The original `_stream_cmd()` skeleton only had `sn/cmdId/cmdFunc/params`.
All seven additional fields are required or the device acknowledges nothing and its state does
not change:

| Field | Required value | Purpose |
|-------|---------------|---------|
| `dirDest` | `1` | routing direction to device |
| `dirSrc` | `1` | routing direction from client |
| `dest` | `2` | destination node identifier |
| `needAck` | `True` | request device acknowledgement |
| `from` | `"ecoflow-python"` | client identifier string |
| `id` | `str(next(_seq))` | monotonic per-command sequence number |
| `version` | `"1.0"` | protocol version |

**Fix (PR #6 commit "fix: STREAM command envelope — add dirDest/dirSrc/dest/needAck/from/id/version", squash-merged as "feat: STREAM relay commands — validated against real BK11/BK31 hardware"):** `_stream_cmd()` in `devices/stream_ultra.py` now builds the
full envelope before passing to `_publish()`:

```python
def _stream_cmd(self, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": "ecoflow-python",
        "id": str(next(_seq)),
        "version": "1.0",
        "sn": self.sn,
        "cmdId": 17,
        "cmdFunc": 254,
        "dirDest": 1,
        "dirSrc": 1,
        "dest": 2,
        "needAck": True,
        "params": params,
    }
```

**Generalised (2026-09):** `BaseDevice._publish()` now fills in `from`, `id`, `version`
and `sn` for **every** public-API set command (plugs, batteries, ...), matching the
tolwi reference's `JSONMessage` envelope. Payload keys override the defaults, so
`_stream_cmd()` output is sent unchanged.

This applies to **ALL STREAM commands**: `set_relay2`, `set_relay3`, `set_grid_export`,
`set_backup_reserve`, `set_self_powered_mode`, `set_ai_schedule_mode`.

**Source:** tolwi/hassio-ecoflow-cloud `stream_ac.py` `switches()` — production-validated
envelope used by a deployed Home Assistant integration.

**Validated live (2026-06-01):** `set_relay2(on=True)` / `set_relay2(on=False)` confirmed
working on BK11 STREAM Ultra — `relay2_on` toggled correctly as verified by REST `/quota/all`
refresh after each command.

---

### Quirk 14: Some MQTT Pushes Are Wrapped — REST Is Flat

REST `/quota/all` returns a flat dict. MQTT `/quota` pushes are flat for some
families and wrapped in a family-specific envelope for others:

| Family | MQTT push | Equivalent REST keys | Evidence |
|--------|-----------|----------------------|----------|
| STREAM, Smart Meter | flat: `{"powGetSysGrid": 695.0, ...}` | same keys | **recorded live 2026-09-27** |
| Smart Plug | `{"addr": .., "cmdFunc": 2, "cmdId": 1, "params": {"watts": 1030}}` — note `params`, not `param`; a heartbeat every ~2 s carrying only changed keys (`watts` only when the load changes) | `2_1.watts` | **recorded live 2026-09-27** |
| PowerStream | `{"cmdFunc": .., "cmdId": .., "param": {...}}` | `<f>_<id>.*` | tolwi reference |
| DELTA Pro 3 | `{"params": {...}}` | same keys | tolwi reference (unverified here) |
| DELTA 2 / RIVER 2 | `{"typeCode": "pdStatus", "params": {"soc": 80}}` | `pd.soc` | tolwi reference |

Before 2026-09-27 this table claimed STREAM/Smart Meter pushes were wrapped in
`{"params": ...}`; the first live recording (`tests/recordings/live-20260927/`)
showed they are flat. Flat pushes pass through the normaliser unchanged.

STREAM pushes are partial and topic-specific: power flows arrive every few
seconds, and each unit's battery pack arrives as its own flat push carrying
`soc`, `vol` (mV), `cycles`, `designCap`, `fullCap`, `remainCap`, `packSn`
(never `bmsBattSoc`/`vBat`). REST `/quota/all` for STREAM has only ~15 system
keys (`cmsBattSoc`, `powGet*`, relays, limits) — cascade-slave AC Pros report
`cmsBattSoc = 0`, so their real SOC is only visible via the pack push. The Smart
Meter's REST `quota/all` data is **empty** even when online; it reports only
over MQTT (`gridConnectionPowerL1..3`, `gridConnectionVolL1..3`, `powGetSysGrid`).

`MqttTransport.dispatch_message()` runs `transport/payload.normalize_quota_payload()`
so device parsers only ever see the REST layout. Before this, MQTT updates parsed
into all-zero statuses. `BatteryStatus` additionally groups flat `pd.*`/`inv.*`
keys into per-module dicts.

---

### Quirk 15: Smart Plug Pushes a Transient `volt: 0` (recorded 2026-09-27/28)

In both live recordings, every `volt` update from the Smart Plug arrived as a **pair**: first
`volt: 0`, then the real mains voltage about 2 s later (4 of 4 pairs in 11 minutes).
A plug that is reporting is powered, so the 0 is never real. `SmartPlugDevice` keeps the
last known voltage when a push says 0.

The service twin found this. The replay test failed about 1 run in 3, whenever its snapshot
fell inside the 0.1 s window (20× replay) between the pair. Live, it would show as a 0 V
glitch in any app.

---

## Public API Device Limitations (Confirmed Live)

### Wave 3 Returns Error 1006

The Wave 3 AC (SN prefix `AC71`) is **not** supported by the public Developer API. Any REST or
public MQTT query for a Wave 3 device returns:
```json
{"code": "1006", "message": "current device is not allowed to get device info"}
```
Use `Wave3Connection` from `ecoflow.private` instead. The `EcoFlowClient` will discover the
device and route it to `client.wave3_units`, but data fields will be unpopulated.

### STREAM Devices Do Not Return productName

The BK-series STREAM devices (BK11, BK31) return no `productName` in the device list API
response. Device class routing falls back to the SN prefix map in `const.py`:
```python
SN_PREFIX_TO_MODEL = {"BK11": "STREAM Ultra", "BK31": "STREAM AC Pro", ...}
```
If you add a new device type, add its SN prefix to this map.

### SmartHomePanelDevice Has No Typed Model

`SmartHomePanelDevice.status` returns a raw `dict`, not a typed dataclass. There is also no
`client.panels` collection — panels are tracked in `_all_typed` internally and receive MQTT
updates but are not exposed at the top level. This is a known incomplete area.

### MicroInverterDevice Borrows SmartMeterData

`MicroInverterDevice` temporarily reuses `SmartMeterData` as its status type. The PowerStream
600W and 800W share the same `productName` (`"PowerStream"`) and are currently indistinguishable
via the API. This is labeled "temporary" in the code.

---

## Running Tests

```bash
# Unit tests only (fast, no real devices needed) — includes tests/test_recordings.py
uv run pytest -m "not integration and not write_integration" -q

# Live tests NEVER run without an explicit --live tier (even with tests/.env).
# Full runbook: docs/api/live-testing.md. Never run live tests in CI.
uv run pytest tests/e2e/test_live_rest.py --live=rest -v -s     # REST only, HA-safe
uv run pytest tests/e2e -m integration --live=mqtt -v -s        # takes MQTT session

# Replay the live REST/MQTT modules against the service twin (what CI runs)
uv run pytest tests/e2e --live=replay -v

# Run the service twin for an app or agent (docs/api/digital-twin.md)
uv run ecoflow-twin serve --recording tests/recordings/live-20260928/recording.json

# Record a redacted session for replay (REST-only by default; --mqtt-seconds N takes
# the MQTT session). Owner reviews + approves before commit.
uv run python scripts/capture_vectors.py --record live-YYYYMMDD
uv run python scripts/capture_vectors.py --check-signature

# Wave 3 write tests (EXPLICIT OPT-IN ONLY — touches real hardware)
ECOFLOW_ENABLE_WRITE_TESTS=true \
uv run pytest tests/e2e/write/ -m write_integration -v -s --timeout=120 --enable-write-tests

# Quality checks (run before every commit)
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

---

## Environment Setup (`tests/.env`)

```dotenv
ECOFLOW_ACCESS_KEY=your_developer_api_key
ECOFLOW_SECRET_KEY=your_developer_secret_key
ECOFLOW_REGION=EU          # or US

# Private API (Wave 3 only)
ECOFLOW_EMAIL=your@ecoflow-app-email.com
ECOFLOW_PASSWORD=your_ecoflow_app_password
ECOFLOW_WAVE3_SN=AC71XXXXXXXXXX   # your Wave 3 serial number

# Explicit opt-in for write tests (turns on/off real hardware)
ECOFLOW_ENABLE_WRITE_TESTS=true
```

Copy `tests/.env.example` to `tests/.env` and fill in your values. Integration tests are skipped
automatically when the file is absent (as in CI). The `.env` file is git-ignored — never commit it.

---

## Key Design Decisions

### Two API Paths (Never Mix Them)

The public Developer API and private API are completely separate stacks that share nothing:

| | Public API | Private API |
|-|-----------|-------------|
| Auth | `EcoFlowCredentials` (accessKey/secretKey) | `PrivateCredentials` (email + password) |
| Transport | `RestTransport` + `MqttTransport` | Direct `aiomqtt` in `Wave3Connection` |
| Wire format | JSON | Protobuf (XOR-encrypted when `enc_type==1 and src!=32`) |
| MQTT broker | `mqtt-e.ecoflow.com` (EU) / `mqtt.ecoflow.com` (US) | `mqtt.ecoflow.com` (global) |
| Entry point | `EcoFlowClient` | `Wave3Connection` |

`Wave3Connection` uses `aiomqtt` directly, NOT `MqttTransport`. This is intentional — `MqttTransport`
calls `json.loads()` on every message and would silently discard all Protobuf content.

### Stable MQTT Client IDs (Critical Invariant)

**Never use random UUIDs as MQTT client IDs.** The EcoFlow broker limits accounts to ~10 unique
IDs per day. All client IDs in this library are deterministic SHA-256 hashes of the account
identifier. If you modify any MQTT connection code, preserve this invariant. There is no
workaround for a burnt quota except waiting for midnight UTC.

### Error 135 Fail-Fast

On the **first** connect attempt, error 135 raises `EcoFlowConnectionError` immediately with
a diagnostic message. It does NOT retry. Subsequent disconnects after a working session do retry
with exponential backoff (the session may have been transiently stolen).

### Device Discovery Pattern

`EcoFlowClient.connect()` calls `rest.list_devices()` then routes each device:
1. By `productName` → `_DEVICE_CLASS_MAP` in `client.py` (primary)
2. By SN prefix (first 4 chars) → `SN_PREFIX_TO_MODEL` in `const.py` (fallback for BK-series
   where the API omits `productName`)
3. Falls through to `DiscoveredDevice` in `client.unknown_devices` if neither matches

### REST vs MQTT for Reads

All `device.refresh()` calls use REST (always reliable, no quota). MQTT subscriptions deliver
real-time pushes but require a live connection. Tests that call `await device.refresh()` use
REST. Tests that `await asyncio.sleep(N)` and check `device.status` rely on MQTT. Both work —
but `device.status` will be `None` if the MQTT connection failed.

### Write Tests Safety (Two Opt-Ins Required)

Write integration tests (`@pytest.mark.write_integration`) physically control real hardware. They
require two independent opt-ins to prevent accidental execution:

1. `ECOFLOW_ENABLE_WRITE_TESTS=true` in `tests/.env`
2. `--enable-write-tests` flag on the pytest command

**NEVER run write tests accidentally.** They will power real hardware on and off.

### Wave3Device + Private API (rest=None)

When `Wave3Connection` creates a `Wave3Device`, it passes `rest=None`. This is intentional.
`refresh()` returns the current cached status without a REST call. Write commands go through
`Wave3Connection.send_raw()` (which encodes Protobuf), not `BaseDevice._publish()` (which would
send JSON to a public MQTT topic that the Wave 3 doesn't monitor).

### No Real SNs in Code

Real device serial numbers are **never** hardcoded in source or test files. Unit tests use fake
SNs (`AC71TESTSN000001`, `BK11TESTSN000001`, etc.). E2E tests read SNs from environment
variables (`os.environ["ECOFLOW_WAVE3_SN"]`) and skip with `pytest.skip` if not set.
**Enforce this in any code you write or review.**

### `on_update` Callback Pattern

All typed devices support `device.on_update(callback)` for synchronous callbacks that fire on
every incoming MQTT update. For async streaming, use `device.events()` (each iterator gets its
own ordered buffer of 100 updates; oldest dropped if the consumer falls behind), or
`await device.wait_for_update()` inside `asyncio.timeout(...)` for the next one.
`EcoFlowClient.events()` merges all devices as `{"sn", "product_name", "data"}`.
Before 2026-09, `device.events()` never yielded (it polled a field nothing set) and
`client.events()` was a stub.

`EcoFlowClient(..., enable_mqtt=False)` is REST-only: it never opens MQTT, so it can run
alongside Home Assistant without taking the account's single session (Quirk 2).

---

## Branch and PR Conventions

- All feature work on `feat/` branches
- PRs only into `main`
- CI runs: `ruff format --check`, `ruff check`, `pyright`, `pytest` (unit tests), then
  `pytest tests/e2e --live=replay` (recorded sessions, offline — no secrets)
- Live tests (read and write) are never run in CI — they would share the owner's MQTT
  session. Run them ad hoc: `docs/api/live-testing.md`

---

## Known Incomplete Areas

- **`SmartHomePanelDevice`**: Returns raw `dict` from `refresh()`, no typed model. Not exposed
  as `client.panels` — devices go into `_all_typed` only.
- **`MicroInverterDevice`**: Reuses `SmartMeterData` (labeled temporary). PowerStream 600W and
  800W are indistinguishable via API.
- **STREAM relay write commands** (`set_relay2`, `set_relay3`): **Validated on 2026-06-01.**
  `set_relay2(on=True/False)` confirmed working on BK11 STREAM Ultra — `relay2_on` toggled
  correctly via REST `/quota/all` refresh. The full envelope quirk (Quirk 13) was the missing
  piece. `set_relay3` follows identical envelope structure and is expected to work the same way.
- **Public API MQTT for STREAM devices**: validated live 2026-09-27 and recorded
  (`tests/recordings/live-20260927`, `live-20260928`).
- Full per-command status (live / recorded / reference / suspect / gap):
  `docs/validation-status.md`.

---

## Architecture, Decisions and History

- `docs/architecture.md` — current Mermaid diagrams: system context, modules, read/command
  flows, test tiers, recording pipeline.
- `docs/decisions/` — ADRs with evidence. **Read the relevant one before changing behaviour
  it describes.** Cite PR numbers and commit titles, never SHAs (history was rewritten once).
- `docs/history.md` — timeline and lessons learned.
- `docs/validation-status.md` — what is proven on hardware; update it after every live run.
- `docs/diagrams/` — the v0.3.0 Graphviz diagrams, kept as a historical snapshot (partly
  outdated; see its README).

MQTT guide with full protocol details: `docs/api/mqtt-guide.md`
