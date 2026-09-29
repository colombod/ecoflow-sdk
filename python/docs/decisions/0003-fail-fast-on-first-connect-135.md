# 0003 — Fail fast on MQTT 135 at first connect

- **Status:** Accepted
- **Date:** 2026-06-01, extended to Wave 3 on 2026-09-28
- **Related:** AGENTS.md Quirks 2 and 5; issue #19; PR #11

## Context
Both brokers use code 135 for two different conditions:
- the daily client-ID quota is spent (ADR [0002](0002-stable-mqtt-client-ids.md));
- **another session already holds the account**, for example Home Assistant.

Neither condition clears by retrying with the same ID a second later. Each retry can also cost another quota slot.

## Decision
- **First connect** gets 135 → raise `EcoFlowConnectionError` immediately, with a message that names both causes and what to do.
- **Reconnect after a working session** gets 135 → retry with exponential backoff (1 s up to 300 s). The session may have been taken over for a short time.

`MqttTransport` and `Wave3Connection` behave the same way.

## Consequences
- The first-connect error message is the diagnosis; keep it specific.
- The SDK cannot share one account with another live integration. `EcoFlowClient(enable_mqtt=False)` gives REST-only reads that never take the session (ADR [0007](0007-event-streams.md)).
- On Windows, the default Proactor event loop cannot run aiomqtt. `connect()` fails fast there too, instead of timing out.

## Evidence
- AGENTS.md Quirk 5 (0.3.0).
- Live 2026-09-27: `Wave3Connection` retried 135 silently and surfaced it as a generic 15 s `TimeoutError`. Fixed by the commit "fix: Wave3Connection fails fast on MQTT 135 at first connect" (closes #19).
- Commit "fix: fail fast on the Windows Proactor event loop".
