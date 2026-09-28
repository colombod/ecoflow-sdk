# EcoFlow service twin — core (Twin 1)

- **Status:** draft for review
- **Tracking:** epic #21, this sub-project #22 (beads `ef-quc.1`)
- **Builds on:** PR #11 (record/replay simulator, live recording `live-20260927`)

## Why

Apps, integrations and CI need EcoFlow's cloud without EcoFlow's cloud: no
credentials, no rate limits, no one-MQTT-session-per-account fights with Home
Assistant, no hardware side effects. Following StrongDM's *Digital Twin
Universe* and Amplifier's DTU, the twin is a **behavioural clone at the network
boundary**: clients connect over the real protocols (HTTPS REST, MQTT over TLS)
and cannot tell it from EcoFlow, except that it answers from a recording.

PR #11's simulator patches `httpx` and `aiomqtt` inside the test process. That
proves the SDK's parsing, but not "connecting from the real perspective", and
nothing outside Python can use it. Twin 1 replaces it with a real server.

## Scope

**In:**

- Recording format v2.
- A twin server for the **public** API (REST + MQTT broker) and the **private
  Wave 3** API (login + certification REST + MQTT broker with protobuf
  playback).
- Emulation of the service behaviours we have observed.
- SDK endpoint overrides.
- An `ecoflow-twin serve` CLI.
- CI moved onto the twin.

**Out (later sub-projects):**

- A public recorder CLI (Twin 2 — the existing `scripts/capture_vectors.py`
  keeps working and writes v2).
- Docker, Amplifier DTU manifest, DNS rewriting (Twin 3).
- The mobile-app spike (Twin 4).
- Stateful simulation beyond command acknowledgement (see *Commands*).

## Package and dependencies

- A separate top-level package, `ecoflow_twin`, in the same distribution under
  `python/src/ecoflow_twin/`, installed with the extra `ecoflow-python[twin]`.
  The SDK (`ecoflow`) never imports it, so the SDK's runtime dependencies stay
  `httpx` + `aiomqtt`.
- New dependencies, in the `twin` extra only:
  - `aiohttp` for the HTTPS server.
  - `cryptography` to generate the CA and server certificates.
- The MQTT broker is **our own minimal MQTT 3.1.1 implementation** (asyncio
  streams + TLS), not a third-party broker. Two reasons:
  - It must reproduce EcoFlow-specific refusals exactly, as described under
    *Emulated behaviours*.
  - The subset EcoFlow's clients use is small: CONNECT/CONNACK,
    SUBSCRIBE/SUBACK, PUBLISH QoS 0/1 with PUBACK, PINGREQ/PINGRESP and
    DISCONNECT. Retained messages, wills and QoS 2 are not needed.
- Real clients (aiomqtt/paho and the `mosquitto_sub` CLI) are used in tests to
  keep it honest.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `recording.py` | Load, validate and migrate recordings (v1 → v2). Pure data. | — |
| `timeline.py` | Clock and playback: time-compressed, looping iterator of pushes; per-device current state (last REST body merged with pushes up to *now*). | recording |
| `certs.py` | Create or load a local CA and a server certificate for `localhost`, `127.0.0.1`, `api-e/api/mqtt-e/mqtt.ecoflow.com`. Write the CA to `<state dir>/ca.pem` for clients. | cryptography |
| `auth.py` | Verify EcoFlow's REST signature (independent of `ecoflow.auth`, moved from `tests/support/replay.py`), the private login, and broker credentials. | — |
| `rest.py` | aiohttp app. **Public:** `GET device/list`, `GET device/quota/all`, `GET certification`, `PUT device/quota` (commands). **Private:** `POST /auth/login`, `GET /iot-auth/app/certification`. | timeline, auth |
| `broker.py` | Minimal MQTT 3.1.1 broker over TLS. Topic routing; per-account session rules; delivers timeline pushes to subscribers; answers `/set` with `/set_reply`. | timeline, auth |
| `server.py` | Composes one or two REST apps and two brokers (public and private) on configurable ports; lifecycle; the `TwinEndpoints` it exposes. | all |
| `cli.py` | `ecoflow-twin serve --recording PATH [--speed 20] [--rest-port 0] [--mqtt-port 0] [--private-mqtt-port 0] [--state-dir DIR]`. Prints the endpoints plus the CA path as JSON so scripts and agents can consume it. | server |

## Recording format v2

A superset of v1:

- Adds `"version": 2`.
- Adds an optional `private` section for the Wave 3:
  - `login`: the shape of the login response, with account fields redacted.
  - `certification`.
  - `mqtt`: a timeline of `{t, sn, topic_kind, payload_b64}`. Each entry holds
    the **raw protobuf bytes**, the XOR-encrypted `pdata` exactly as received,
    so the SDK's decoder runs for real.
- v1 files load as v2 with no `private` section. `live-20260927` stays valid
  unchanged.
- The Wave 3 capture in `capture_vectors.py` is added in this sub-project, because
  the twin needs data to play back.

## Emulated behaviours

These were observed live. Each is covered by a test against the twin.

| Behaviour | Source |
|---|---|
| REST signature = HMAC-SHA256 over sorted params plus accessKey/nonce/timestamp; a wrong signature → `8521` | spec + live |
| A GET with `Content-Type: application/json` is verified *without* its query → `8521` | live 2026-09-27 |
| Public API quota for Wave 3 → `1006`; the Smart Meter's quota is `data: {}` | recording |
| `certification` returns the twin's broker host and port, and the account `open-<id>` | spec |
| **One MQTT session per account**: a second CONNECT → return code 5, which surfaces as 135; the first session keeps running | AGENTS.md Quirk 2 |
| **~10 unique client IDs per account per day**: the 11th distinct ID → 135 (a configurable limit; the counter resets when the twin restarts) | Quirk 1 |
| **Private broker: client ID must be `ANDROID_<32 hex>_<userId>`**, otherwise 135 | live 2026-09-27 |
| Wave 3 is silent until a GET on `/app/{userId}/{sn}/thing/property/get`, then sends its state dump | Quirk 8 |
| Pushes per family as recorded (flat STREAM/meter, plug `params` envelope, battery-pack pushes) | recording |

## Commands

The twin accepts `PUT device/quota` and MQTT `/set` for known devices:

- It checks the signature and the envelope (Quirk 13), and answers on
  `/set_reply` with `code 0`.
- For the few command keys the SDK can already send and whose effect we have
  seen live, it applies the effect to the device state:
  - STREAM `cfgRelay2Onoff`/`cfgRelay3Onoff` → `relay2Onoff`/`relay3Onoff`
  - `cfgBackupReverseSoc`
  - `cfgFeedGridMode`
  - `cfgEnergyStrategyOperateMode.*`
  - plug `plugSwitch` → `2_1.switchSta`
- Unknown keys are acknowledged and logged, and change nothing.
- Anything beyond that (simulating the charge curve, power flows) is out of
  scope.

## SDK changes (small, backwards compatible)

- `ecoflow.Endpoints` — a frozen dataclass with:
  - `rest_base`, `private_rest_base`
  - `private_mqtt_host`, `private_mqtt_port`
  - `ca_file: str | None`
- Defaults are today's EcoFlow values.
- `EcoFlowClient(..., endpoints=...)` and `Wave3Connection(..., endpoints=...)`
  accept it.
- `Endpoints.from_env()` reads `ECOFLOW_REST_BASE` and friends, so any app built
  on the SDK can be pointed at a twin without code changes.
- `ca_file` builds the TLS context for both httpx and aiomqtt.
- No other behaviour changes. The public MQTT host already comes from
  `certification`.

## CI and tests

- `tests/support/replay.py` is replaced. A session fixture starts the twin
  **in-process** (`TwinServer` on ephemeral ports), and `--live=replay` points
  the SDK at it through `Endpoints`. The same e2e modules and the same
  recordings are used, and traffic now goes over real sockets with TLS.
- `tests/test_recordings.py` keeps its PII guard and redactor tests. Its
  "replay server" tests move to `tests/twin/`.
- New unit tests, in `tests/twin/`:
  - Broker protocol, driven by aiomqtt as the client.
  - Each emulated behaviour in the table above.
  - v1 → v2 migration.
  - Certificate generation.
  - CLI output.
- A CI job runs `ecoflow-twin serve` as a subprocess and connects with
  `mosquitto_sub` and `curl`. This proves non-Python clients work.

## Error handling

- Malformed MQTT packets drop that connection, not the broker.
- An unknown REST route → 404 in EcoFlow's JSON error shape.
- A recording that fails validation → the CLI exits with a message naming the
  field.
- The twin never makes outbound network calls.

## Success criteria

1. `pytest tests/e2e --live=replay` passes against the twin over TLS on
   Windows and Linux, for `synthetic` and `live-20260927`.
2. Every row in *Emulated behaviours* has a passing test.
3. A Wave 3 recording plays back through `Wave3Connection` pointed at the twin
   and decodes to the recorded `Wave3Status`.
4. `ecoflow-twin serve` plus `curl` (signed) plus `mosquitto_sub` works from a
   shell.
5. PR #11's CI step is replaced by the twin, and CI is green.

## Risks

- **The MQTT broker is ours.** Keep it to the subset above, test it with two
  independent clients, and cap it at about 400 lines.
- **Recording the Wave 3 protobuf live** needs the private session, so the
  EcoFlow app must be closed. It is a one-off, and a synthetic Wave 3 timeline
  built from the existing decoder test fixtures covers CI until then.
