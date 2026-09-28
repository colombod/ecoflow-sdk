# 0006 — Common envelope on every public-API command

- **Status:** Accepted
- **Date:** 2026-06-01, generalised 2026-09-27
- **Related:** AGENTS.md Quirk 13; PR #6, PR #10

## Context
STREAM devices **silently ignore** a set command that lacks the full envelope: there is no error and no state change. The first skeleton sent only `sn/cmdId/cmdFunc/params`. The working envelope is:
- `cmdId 17`, `cmdFunc 254`
- `dirDest 1`, `dirSrc 1`, `dest 2`, `needAck true`
- `from`, `id` (monotonic sequence), `version "1.0"`, `sn`

It was taken from the tolwi reference integration, which runs in production.

## Decision
- `BaseDevice._publish()` adds `from/id/version/sn` to **every** public-API command.
- STREAM's `_stream_cmd()` adds the routing fields.
- Keys in the payload override the defaults, so a device-specific envelope is sent unchanged.

## Consequences
- Plugs and batteries get the same envelope as the reference integration.
- Command acknowledgements on `/set_reply` are not consumed yet. A command that the device ignores still looks like success to the caller. See [validation-status.md](../validation-status.md).
- Only `set_relay2` has been validated live. Treat the other STREAM, plug and battery writes as unverified.

## Evidence
- Live 2026-06-01 on a STREAM Ultra: `set_relay2(on=True/False)` toggled `relay2_on`, confirmed by a REST refresh. Commit "feat: STREAM relay commands — validated against real BK11/BK31 hardware" (PR #6).
- Source: tolwi/hassio-ecoflow-cloud `stream_ac.py`.
