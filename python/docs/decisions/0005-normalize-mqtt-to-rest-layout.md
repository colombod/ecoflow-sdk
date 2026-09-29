# 0005 — Convert every MQTT push to the REST key layout

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** AGENTS.md Quirk 14; PR #10, PR #11; `transport/payload.py`

## Context
REST `quota/all` returns one flat dict. MQTT pushes differ by device family:

| Family | MQTT push shape |
|---|---|
| STREAM, Smart Meter | flat |
| Smart Plug | `{addr, cmdFunc: 2, cmdId: 1, params}` (REST keys `2_1.*`) |
| PowerStream | `{cmdFunc, cmdId, param}` |
| DELTA 2 / RIVER 2 | `{typeCode, params}` (REST keys `pd.*` and similar) |

Before 2026-09 the parsers were fed raw pushes, and live MQTT produced all-zero statuses.

## Decision
`MqttTransport.dispatch_message()` runs `normalize_quota_payload()` on every push. Device parsers only ever see the REST layout. Every typed device keeps **one accumulated raw dict**, and REST `refresh()` merges into the same dict instead of replacing it.

## Consequences
- There is one parser per model, and a REST snapshot and an MQTT stream can be compared key by key. The replay tier does that for every recording.
- The merge matters. REST has only about 15 STREAM system keys, and the battery pack arrives only over MQTT. Replacing the state on `refresh()` dropped a cascade-slave AC Pro back to 0 % SOC.
- Stale-message filtering drops only *strictly older* timestamps, because chunks of one state dump can share a timestamp.

## Evidence
- The flat STREAM/meter and plug `params` shapes were recorded live on 2026-09-27 (`tests/recordings/live-20260927`). Earlier docs claimed STREAM pushes were wrapped; the recording disproved that, and flat pushes pass through unchanged.
- PowerStream and DELTA shapes come from the tolwi reference only and have not been verified here.
- Commits "fix: read STREAM battery-pack pushes (soc, vol)" and "fix: STREAM refresh() merges REST into MQTT state".
- The negative control in `tests/test_recordings.py` shows that skipping normalisation fails the agreement check.
