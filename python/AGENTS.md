# AGENTS.md — ecoflow-python

## What This Library Does

`ecoflow-python` is a typed async Python SDK for monitoring and controlling EcoFlow energy
devices. It provides two completely separate API paths: the **public Developer API**
(accessKey/secretKey via `EcoFlowClient`) which covers most devices through REST + JSON MQTT,
and the **private API** (email/password + Protobuf via `Wave3Connection`) which is required for
Wave 3 portable AC units because EcoFlow's public API returns error 1006 for that model.

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
│   └── mqtt.py       — MqttTransport (aiomqtt, TLS, auto-reconnect)
├── devices/          — 9 device classes (BaseDevice + 8 typed subclasses) + DiscoveredDevice
├── models/           — Pure dataclass status snapshots per device type
└── private/          — Wave 3 private API (optional, requires protobuf extra)
    ├── auth.py       — login(email, password) → PrivateCredentials
    ├── connection.py — Wave3Connection (direct aiomqtt, Protobuf, auto-reconnect)
    └── proto/        — decoder.py, encoder.py, wave3_pb2.py (vendored)
```

### Device Classes (`devices/`)

| File | Class | Typed collection on `EcoFlowClient` |
|------|-------|--------------------------------------|
| `base.py` | `BaseDevice` | — (abstract base) |
| `battery.py` | `BatteryDevice` | `client.batteries` |
| `plug.py` | `SmartPlugDevice` | `client.plugs` |
| `meter.py` | `SmartMeterDevice` | `client.meters` |
| `inverter.py` | `MicroInverterDevice` | `client.inverters` |
| `wave3.py` | `Wave3Device` | `client.wave3_units` |
| `stream_ultra.py` | `StreamUltraDevice` | `client.stream_units` |
| `stream_ac_pro.py` | `StreamAcProDevice` | `client.stream_units` (subclass of `StreamUltraDevice`) |
| `panel.py` | `SmartHomePanelDevice` | none — added to internal `_all_typed` only |
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
├── EcoFlowConnectionError      ← network / transport failure
├── EcoFlowDeviceNotFoundError  ← SN not on account (carries .sn attr)
├── EcoFlowTimeoutError         ← command or query timed out
├── EcoFlowDeviceOfflineError   ← action on offline device (carries .sn attr)
└── EcoFlowCommandError         ← device rejected a command
```

### Test Structure

```
tests/
├── test_*.py                         — Unit tests (mocked, no real devices)
│   ├── test_models_wave3_private.py  — ACTIVE_PAYLOAD/STANDBY_PAYLOAD fixtures from real device
│   └── test_private_decoder.py       — XOR decryption + Protobuf dispatch tests
├── conftest.py                       — Credential helpers (skip if tests/.env missing)
└── e2e/
    ├── test_read.py                  — Read integration tests (real devices, @pytest.mark.integration)
    ├── test_private_read.py          — Wave 3 private API read tests (@pytest.mark.integration)
    └── write/
        └── test_wave3_commands.py    — Wave 3 write tests (@pytest.mark.write_integration,
                                        requires ECOFLOW_ENABLE_WRITE_TESTS=true)
```

---

## Running Tests

```bash
# Unit tests only (fast, no real devices needed)
uv run pytest -m "not integration and not write_integration" -q

# Integration read tests (requires real devices + tests/.env)
uv run pytest -m "integration" -v -s --timeout=60

# Wave 3 write tests (EXPLICIT OPT-IN ONLY — touches real hardware)
ECOFLOW_ENABLE_WRITE_TESTS=true \
uv run pytest tests/e2e/write/ -m write_integration -v -s --timeout=120 --enable-write-tests

# Quality checks
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
automatically when the file is absent (as in CI).

---

## Key Design Decisions

### Two API Paths (Never Mix Them)

The public Developer API and private API are completely separate stacks:

| | Public API | Private API |
|-|-----------|-------------|
| Auth | `EcoFlowCredentials` (accessKey/secretKey) | `PrivateCredentials` (email + password) |
| Transport | `RestTransport` + `MqttTransport` | Direct `aiomqtt` in `Wave3Connection` |
| Wire format | JSON | Protobuf (XOR-encrypted when `enc_type==1`) |
| MQTT broker | `mqtt-e.ecoflow.com` (EU) / `mqtt.ecoflow.com` (US) | `mqtt.ecoflow.com` (global) |
| Entry point | `EcoFlowClient` | `Wave3Connection` |

They share nothing: not auth, not transport, not brokers. Do not try to use `MqttTransport` for
Wave 3 — it calls `json.loads()` on every message and silently discards all Protobuf content.

### Device Discovery Pattern

`EcoFlowClient.connect()` calls `rest.list_devices()` then routes each device:
1. By `productName` → `_DEVICE_CLASS_MAP` in `client.py` (primary)
2. By SN prefix (first 4 chars) → `SN_PREFIX_TO_MODEL` in `const.py` (fallback, for devices where
   the API omits `productName`, e.g., BK-series STREAM devices)
3. Falls through to `DiscoveredDevice` in `client.unknown_devices` if neither matches

### MQTT Client ID Generation (QUIRK)

The EcoFlow public API `/certification` endpoint does **not** return a `clientId`. We generate:
`ANDROID_{UUID}_{certificateAccount}`. An empty `clientId` causes MQTT error 135 (Not Authorized).
Confirmed broken 2026-05-31 during STREAM relay investigation.

### Private API MQTT (Wave 3 QUIRKS)

1. **Password encoding**: Password MUST be base64-encoded before POST to `/auth/login`.
2. **Two-step auth**: login → bearer token → GET `/iot-auth/app/certification` (with `userId` in
   the GET request body, form-encoded) → MQTT credentials.
3. **State trigger**: After subscribing, publish a GET to `/app/{userId}/{sn}/thing/property/get`
   to trigger a full state dump. Without this the device is silent until its next heartbeat.
4. **XOR encryption**: Incoming messages are XOR-encrypted when `enc_type==1 and src!=32`:
   `byte ^ (seq & 0xFF)`. The decoder handles this transparently.
5. **Broker**: `mqtt.ecoflow.com:8883` (NOT `mqtt-e.ecoflow.com` used by the public EU API).

### Write Tests Safety

Write integration tests (`@pytest.mark.write_integration`) physically control devices. They
require **two independent opt-ins**:
1. `ECOFLOW_ENABLE_WRITE_TESTS=true` in `tests/.env`
2. Explicit `--enable-write-tests` flag on the pytest command

**NEVER run write tests accidentally.** They will turn on/off real hardware.

### No Real SNs in Code

Real device serial numbers are **never** hardcoded in the source or test files. Unit tests use
fake SNs (`AC71TESTSN000001`, `BK11TESTSN000001`, etc.). E2E tests read SNs from environment
variables (`os.environ["ECOFLOW_WAVE3_SN"]`) and skip with `pytest.skip` if not set.

### Wave3Device + Private API

When `Wave3Connection` creates a `Wave3Device`, it passes `rest=None`. This is intentional and
valid — `refresh()` returns the current cached status without a REST call. Write commands go
through `Wave3Connection.send_raw()` (which encodes Protobuf), not `BaseDevice._publish()`
(which sends JSON to the public MQTT topic).

### `on_update` Callback Pattern

All typed devices support `device.on_update(callback)` to register a synchronous callback that
fires on every incoming MQTT update. For async streaming, use `device.events()` (async generator
yielding the typed status dataclass on each update).

---

## Branch and PR Conventions

- All feature work on `feat/` branches
- PRs only into `main`
- CI runs: `ruff format --check`, `ruff check`, `pyright`, `pytest` (unit + integration)
- Integration tests require real devices and are skipped automatically in CI (no `tests/.env`)

---

## Known Incomplete Areas

- **`SmartHomePanelDevice`**: Returns raw `dict` from `refresh()`, no typed model. Also has no
  dedicated typed collection on `EcoFlowClient` (devices are tracked in `_all_typed` internally
  and receive MQTT updates but are not exposed as `client.panels`).
- **`MicroInverterDevice`**: Reuses `SmartMeterData` for now (labeled as temporary in code).
  PowerStream 600W and 800W share the same `productName` and are indistinguishable via the API.
- **STREAM relay write commands** (`set_relay2`, `set_relay3`): Implemented but MQTT not yet
  validated against real hardware (under investigation in `feat/stream-relay-commands`).
- **Public API MQTT for STREAM devices**: Currently blocked by connection limit on
  `certificateAccount` (under investigation).

---

## Architecture Diagrams

See `docs/diagrams/`:
- `overview.svg` — system overview (two API paths, device types, data flow)
- `device-model.svg` — device class hierarchy + capabilities per device
- `auth-flow.svg` — authentication flow for both API paths
