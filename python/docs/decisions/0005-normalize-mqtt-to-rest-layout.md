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
`MqttTransport.dispatch_message()` runs `normalize_quota_payload()` on every push.
STREAM and Smart Meter accumulate partial readings, merging nonempty REST
refreshes into the same state. STREAM strategy modes are canonicalised to flat
keys so the recorded nested MQTT and flat REST layouts update the same value.
Smart Plug keeps its MQTT accumulator separate from a standalone REST snapshot:
refresh replaces the visible data and receipt map, while later MQTT updates
resume the retained MQTT values and receipt times. This also preserves the
supported legacy heartbeat parser, whose units differ from the REST layout.

## Consequences
- There is one parser per model, and a REST snapshot and an MQTT stream can be compared key by key. The replay tier does that for every recording.
- The merge matters. REST has only about 15 STREAM system keys, and the battery pack arrives only over MQTT. Replacing the state on `refresh()` dropped a cascade-slave AC Pro back to 0 % SOC.
- The base handler compares local receipt times, not publisher timestamps; it
  cannot detect old device measurements or out-of-order vendor delivery.
- STREAM/meter/plug expose `field_received_at` for each normalised raw leaf.
  Partial nested records merge without refreshing unchanged leaf timestamps.
  These are receipt times, not device measurement times. Numeric defaults in
  other model fields remain compatibility placeholders, not observations.

## Evidence
- The flat STREAM/meter and plug `params` shapes were recorded live on 2026-09-27 (`tests/recordings/live-20260927`). Earlier docs claimed STREAM pushes were wrapped; the recording disproved that, and flat pushes pass through unchanged.
- PowerStream and DELTA shapes come from the tolwi reference only and have not been verified here.
- Commits "fix: read STREAM battery-pack pushes (soc, vol)" and "fix: STREAM refresh() merges REST into MQTT state".
- The negative control in `tests/test_recordings.py` shows that skipping normalisation fails the agreement check.
