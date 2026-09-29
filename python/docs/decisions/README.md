# Architecture decision records

Why the SDK is shaped the way it is. Each record states the context, the
decision, its consequences and the **evidence** it rests on: live
observation, a recording, the EcoFlow spec or the
[tolwi/hassio-ecoflow-cloud](https://github.com/tolwi/hassio-ecoflow-cloud)
reference integration. Records cite PR numbers and commit **titles**, never
commit SHAs: history was rewritten once (see [0012](0012-pii-policy.md)) and
SHAs changed.

Before changing behaviour a record describes, read it and the evidence it cites.
Several "obvious simplifications" in this repo were tried and broke real
hardware.

| # | Decision | Status |
|---|---|---|
| [0001](0001-two-separate-api-paths.md) | Two separate API paths: Developer API and the app API for Wave 3 | Accepted |
| [0002](0002-stable-mqtt-client-ids.md) | Stable, deterministic MQTT client IDs in the shape each broker accepts | Accepted |
| [0003](0003-fail-fast-on-first-connect-135.md) | Fail fast on MQTT 135 at first connect, retry only after a working session | Accepted |
| [0004](0004-rest-request-signing.md) | Sign request params; no `Content-Type` on signed GETs | Accepted |
| [0005](0005-normalize-mqtt-to-rest-layout.md) | Convert every MQTT push to the REST key layout before parsing | Accepted |
| [0006](0006-command-envelope.md) | Common envelope on every public-API command | Accepted |
| [0007](0007-event-streams.md) | Event streams from per-subscriber queues | Accepted |
| [0008](0008-live-tests-ad-hoc-never-ci.md) | Live tests are tiered, ad hoc and never run in CI | Accepted |
| [0009](0009-record-replay-as-ci-source-of-truth.md) | Redacted recordings are CI's source of real behaviour | Accepted |
| [0010](0010-service-digital-twin.md) | A service digital twin at the network boundary | Accepted |
| [0011](0011-endpoint-override.md) | Environment-driven endpoint override, loudly logged | Accepted |
| [0012](0012-pii-policy.md) | No real identifiers in any committed file; history purged once | Accepted |
| [0013](0013-history-and-evidence.md) | The history is the record; label evidence; validate before trusting | Accepted |

New record: copy [template.md](template.md), take the next number, link it here.
