# 0002 — Stable MQTT client IDs in the shape each broker accepts

- **Status:** Accepted
- **Date:** 2026-06-01, amended 2026-09-28
- **Related:** AGENTS.md Quirks 1–3; PR #6, PR #11

## Context
- Both brokers allow about **10 unique client IDs per account per day**. After that every CONNECT gets code 135 until midnight UTC.
- The original code used `uuid4()` per connection. One debugging session on 2026-05-31 used up the day's quota, which made the device look broken.
- `/certification` returns no `clientId`. An empty ID also gets 135.
- The app broker additionally accepts only IDs shaped `ANDROID_<32 upper hex>_<userId>`.

## Decision
Client IDs are derived deterministically from the account:
- Developer API: `ecoflow-sdk-<sha256(certificateAccount)[:12]>`.
- App API: `ANDROID_<sha256(userId)[:32].upper()>_<userId>` (`private_client_id()`).

A reconnect reuses the same ID, so a process uses one slot however often it reconnects.

## Consequences
- Never use `uuid4()`, timestamps, PIDs or any per-run suffix in a client ID.
- The shape matters as much as the stability. PR #6 "fixed" the app ID to `ecoflow-private-<hash>`: it was stable, but the broker refused it. Every Wave 3 connection then failed with 135 until PR #11 restored the `ANDROID_` shape. Keep both properties.
- The investigation scripts `wave3_diag.py` and `wave3_wildcard.py` still use random IDs, and are flagged as quota-burning.

## Evidence
- Live 2026-05-31: quota exhausted by random IDs (AGENTS.md Quirk 1).
- Live 2026-09-27: 135 on every app-broker connect with the app closed. Connected, with 4 status updates, after the commit "fix: restore the Wave 3 private-broker client ID format" (PR #11).
- The twin enforces both rules (ADR [0010](0010-service-digital-twin.md)).
