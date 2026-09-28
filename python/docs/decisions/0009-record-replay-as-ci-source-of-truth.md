# 0009 — Redacted recordings are CI's source of real behaviour

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** PR #11, PR #26, PR #29; `scripts/capture_vectors.py`; `tests/recordings/`

## Context
Without live tests in CI (ADR [0008](0008-live-tests-ad-hoc-never-ci.md)), CI needs real device behaviour from somewhere. Hand-written fixtures encode what we *believe* EcoFlow sends. Those beliefs had been wrong twice: the MQTT push shapes and STREAM `chgDsgState`.

## Decision
- The owner records a real session locally with `scripts/capture_vectors.py --record NAME [--mqtt-seconds N]`. It stores **full REST bodies**, including error codes such as the Wave 3's 1006, and the **raw MQTT timeline**, captured before normalisation.
- The `Redactor` rewrites identifiers before the file is written (ADR [0012](0012-pii-policy.md)). The owner reviews the masked-keys list, then commits it.
- `pytest tests/e2e --live=replay` runs **the same test modules as the live tiers** against every recording. From PR #28 on, they run over real sockets against the twin.
- `tests/test_recordings.py` checks MQTT-vs-REST agreement per recording, with a negative control, and runs the PII guard.

## Consequences
- A new recording is a test input. It can find bugs, as the twin's replay did with the plug's `volt: 0` (AGENTS.md Quirk 15).
- Recordings are only as current as their capture date, so re-record after firmware changes.
- There are currently three recordings:
  - `synthetic`: hand-built, for the edge cases (SN-prefix routing, 1006, chunked pushes);
  - `live-20260927`;
  - `live-20260928`: 10 minutes, 1131 pushes, including a grid charge.

## Evidence
- Commits "test: record/replay simulation for CI", "test: add redacted live recording live-20260927" and "test: add redacted live recording live-20260928 (10 min, 1131 pushes)".
- The first live recording corrected the flat-push shapes (ADR [0005](0005-normalize-mqtt-to-rest-layout.md)).
