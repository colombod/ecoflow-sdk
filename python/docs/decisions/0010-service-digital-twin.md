# 0010 — A service digital twin at the network boundary

- **Status:** Accepted (Twin 1a, public API). Wave 3 playback (Twin 1b) is pending in #22.
- **Date:** 2026-09-28
- **Related:** epic #21, #22–#25; PR #28, PR #31; `docs/api/digital-twin.md`; `docs/superpowers/specs/2026-09-28-service-twin-core-design.md`

## Context
PR #11's first replay patched `httpx` and `aiomqtt` inside the test process. That tested the SDK's parsing, but not a real connection, and nothing outside Python could use it. Apps, agents and CI need something that behaves like EcoFlow's cloud: no credentials, no rate limits, no session fights with Home Assistant, no hardware side effects.

## Decision
`ecoflow_twin` is a separate package in the same distribution, installed with the `twin` extra (`aiohttp`, `cryptography`). The SDK never imports it. It provides:
- HTTPS REST for the Developer API, plus its **own minimal MQTT 3.1.1 broker** over TLS.
- **Reproductions of EcoFlow's observed refusals:**
  - signature → 8521, verified independently of `ecoflow.auth`;
  - a GET with a JSON Content-Type → 8521;
  - one session per account;
  - a client-ID limit (default 10).
- Playback of the recorded MQTT timeline in a loop, and command effects for the few keys seen live.
- A local CA. Its private key is never saved; the server key is owner-only.
- `ecoflow-twin serve`, which prints its endpoints as JSON.

## Consequences
- The twin writes its own broker so it can reproduce EcoFlow's exact refusals. It supports only the MQTT subset the clients use: no QoS 2, retained messages or wills.
- The server certificate is valid for EcoFlow's real hostnames. Trust `ca.pem` per process only, never system-wide (PR #31).
- A CI job (`twin-smoke`) drives the twin with `curl` and `mosquitto_sub` to prove non-Python clients work.
- Not done yet:
  - Wave 3 / app-API playback (#22, Twin 1b);
  - a recorder CLI (#23);
  - Docker and DNS (#24);
  - the mobile-app spike (#25).

## Evidence
- The design spec and plan under `docs/superpowers/`.
- Merge "service digital twin (Twin 1a)" (PR #28).
- The twin found a real bug: the Smart Plug's transient `volt: 0`, commit "fix: Smart Plug ignores the transient volt:0 push".
