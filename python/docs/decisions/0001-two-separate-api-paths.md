# 0001 — Two separate API paths

- **Status:** Accepted
- **Date:** 2026-05-31
- **Related:** AGENTS.md Quirks 4, 6–12; `docs/api/private-authentication.md`

## Context
EcoFlow has two unrelated APIs:
- The **Developer API** is for third parties. It uses accessKey/secretKey, signed REST, and JSON MQTT on a broker named by `/certification`.
- The **app API** is what the EcoFlow mobile app uses. It uses email and password, a bearer token, and Protobuf MQTT with XOR obfuscation on `mqtt.ecoflow.com`.

The Wave 3 air conditioner is only reachable through the app API: the Developer API answers `1006` for its quota. The two APIs share no credentials, broker, topics or wire format.

## Decision
One entry point per API, with no shared transport:
- `EcoFlowClient` for the Developer API, built on `RestTransport` and `MqttTransport`.
- `Wave3Connection` for the app API. It uses `aiomqtt` directly and has its own Protobuf encoder and decoder.

A `Wave3Device` created by `Wave3Connection` has `rest=None`. Its writes go through `send_raw()`, never through `BaseDevice._publish()`.

## Consequences
- Each path can follow its own API's rules without special cases.
- Never point `MqttTransport` at the app broker. It calls `json.loads()` on every message, so Protobuf is dropped silently: no error and no data.
- The app API is unofficial and can change without notice. It stays behind the optional `wave3` extra (`protobuf`).

## Evidence
- Live 2026-05-30/31 on a Wave 3: the Developer API returns 1006. Commits "feat: Wave 3 discovery fix + read-only E2E integration tests" and "feat: Wave 3 private API support — read + write commands validated against real hardware".
- The app API protocol was reconstructed from the mobile app's traffic and the tolwi reference; see `private-authentication.md`.
