# 0008 — Live tests are tiered, ad hoc and never run in CI

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** PR #10; `docs/api/live-testing.md`; `tests/conftest.py`

## Context
- The live account is the owner's home installation.
- An MQTT test takes the account's **only** session (ADR [0003](0003-fail-fast-on-first-connect-135.md)), which disconnects Home Assistant.
- Write tests switch real outlets.
- Secrets in CI could leak and would reach a live system on every push.

Up to 0.3.0, a CI job could run the live suite whenever secrets were configured.

## Decision
- Live tests never run in CI. CI holds no EcoFlow secrets.
- Live runs are ad hoc, on a trusted machine, with keys only in the gitignored `tests/.env`.
- Every live test needs an explicit tier; a plain `pytest` never goes live:
  1. `--live=rest`: REST reads only. Safe while Home Assistant runs.
  2. `--live=mqtt`: takes the MQTT session for about 2 minutes. Stop other integrations first.
  3. Writes: **two** opt-ins, `ECOFLOW_ENABLE_WRITE_TESTS=true` *and* `--enable-write-tests`.
- Assistants and contributors ask the owner before anything that takes the MQTT session, and never run writes unless asked.

## Consequences
- CI cannot see live regressions directly. ADRs [0009](0009-record-replay-as-ci-source-of-truth.md) and [0010](0010-service-digital-twin.md) close most of that gap with recordings.
- Behaviour that has never been exercised live must be labelled as such ([validation-status.md](../validation-status.md)).

## Evidence
- The owner required this on 2026-09-27: running live tests from CI "could change things for my live system".
- `tests/test_live_gate.py` and `tests/test_write_gate.py` pin the gates.
