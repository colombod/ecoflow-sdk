# 0004 — Sign the request params; no Content-Type on signed GETs

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** PR #10, PR #11; `auth.py`, `transport/rest.py`

## Context
The Developer API spec signs an HMAC-SHA256 over the request's **sorted, flattened params** followed by `accessKey=…&nonce=…&timestamp=…`. Up to 0.3.0 the SDK signed only the trailing three fields. That happened to work for the param-less endpoints (`device/list`, `certification`), which is all 0.3.0 used.

PR #10 made the SDK sign params as the spec says. It was merged before any live run, and every `quota/all?sn=…` read then failed with `8521 signature is wrong`.

## Decision
- `canonical_params()` + `build_auth_headers(creds, params)` sign the sorted query params, or the flattened JSON body for `PUT`.
- A **GET sends only the auth headers**. With `Content-Type: application/json`, EcoFlow verifies the signature *without* the query params and answers 8521. `PUT` keeps the JSON header.

## Consequences
- Signing is covered by unit tests *and* by an independent verifier in the twin, so a regression fails in CI, not on hardware.
- `scripts/capture_vectors.py --check-signature` shows which signature forms the live API accepts; run it after any signing change.
- The lesson for the project is recorded in ADR [0013](0013-history-and-evidence.md): code that follows the spec is not the same as code validated live.

## Evidence
- Live 2026-09-27: the same signed request fails with the JSON header and succeeds without it. Commit "fix: drop JSON Content-Type on signed GET requests" (PR #11).
- The twin reproduces the behaviour; see the table in `digital-twin.md`.
